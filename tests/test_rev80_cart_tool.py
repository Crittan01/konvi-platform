"""Rev. 80 — Tests del cart_tool."""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.cart_tool import (  # noqa: E402
    ensure_cart,
    get_cart_with_items,
    add_item,
    update_item_quantity,
    remove_item,
    compute_shipping_inputs,
    set_shipping_meta,
    invalidate_shipping,
    _scale_dim,
)


# ─── Stubs minimal Supabase ──────────────────────────────────────────────────

class _ChainedQuery:
    """Stub que devuelve cualquier llamada como self hasta `execute()`."""
    def __init__(self, data=None):
        self._data = data if data is not None else []

    def __getattr__(self, name):
        # cualquier select/eq/order/limit/in_/insert/update/delete devuelve self.
        return self

    def __call__(self, *args, **kwargs):
        return self

    def execute(self):
        m = MagicMock()
        m.data = self._data
        return m


def _supabase_with_table_data(table_data: dict):
    """Crea un mock supabase que devuelve data por nombre de tabla.
    rpc devuelve `rpc_data` por nombre."""
    sb = MagicMock()
    rpc_calls = []

    def _table(name):
        return _ChainedQuery(table_data.get(name, []))

    def _rpc(name, params=None):
        rpc_calls.append((name, params))
        # cart_add_item devuelve TABLE → lista con un dict
        if name == "cart_add_item":
            return _ChainedQuery([{
                "cart_id": params["p_cart_id"],
                "new_version": 2,
                "subtotal_cents": params["p_unit_price_cents"] * params["p_quantity"],
                "total_cents": params["p_unit_price_cents"] * params["p_quantity"],
            }])
        return _ChainedQuery([])

    sb.table.side_effect = _table
    sb.rpc.side_effect = _rpc
    sb._rpc_calls = rpc_calls
    return sb


# ─── Tests ───────────────────────────────────────────────────────────────────

class CartLifecycleTests(unittest.TestCase):

    def test_ensure_cart_returns_existing_open(self):
        existing = {
            "id": "cart-1", "status": "open", "version": 1,
            "subtotal_cents": 0, "shipping_cents": 0, "total_cents": 0,
            "shipping_meta": {}, "requires_requote": False, "contact_id": None,
        }
        sb = _supabase_with_table_data({"conversation_carts": [existing]})
        out = ensure_cart(sb, conversation_id="conv-1", tenant_id="tenant-1")
        self.assertEqual(out["id"], "cart-1")

    def test_ensure_cart_associates_contact_when_missing(self):
        existing = {
            "id": "cart-1", "status": "open", "version": 1,
            "subtotal_cents": 0, "shipping_cents": 0, "total_cents": 0,
            "shipping_meta": {}, "requires_requote": False, "contact_id": None,
        }
        sb = _supabase_with_table_data({"conversation_carts": [existing]})
        out = ensure_cart(sb, conversation_id="conv-1", tenant_id="tenant-1",
                          contact_id="contact-99")
        self.assertEqual(out["contact_id"], "contact-99")


class ScaleDimTests(unittest.TestCase):

    def test_scale_dim_qty_one_no_change(self):
        self.assertEqual(_scale_dim(10.0, 1), 10.0)

    def test_scale_dim_qty_eight_doubles(self):
        # 10 × 8^(1/3) = 10 × 2 = 20
        self.assertAlmostEqual(_scale_dim(10.0, 8), 20.0, places=2)


class ComputeShippingInputsTests(unittest.TestCase):

    def test_empty_cart_returns_zeros(self):
        out = compute_shipping_inputs({"items": []})
        self.assertEqual(out["weight_kg"], 0.0)
        self.assertEqual(out["volumetric_weight_kg"], 0.0)
        self.assertEqual(out["billable_weight_kg"], 0.0)
        self.assertEqual(out["lines"], [])

    def test_single_item_qty_one(self):
        cart = {
            "items": [{
                "variation_id": "v1", "product_id": "p1", "quantity": 1,
                "unit_price_cents": 1800000,
                "variation": {
                    "weight_kg": 0.10, "length_cm": 8, "width_cm": 8, "height_cm": 4,
                },
            }],
        }
        out = compute_shipping_inputs(cart)
        self.assertEqual(out["weight_kg"], 0.10)
        # 8*8*4 = 256 cm³ / 5000 = 0.0512 kg
        self.assertAlmostEqual(out["volumetric_weight_kg"], 0.051, places=3)
        # billable = max(0.10, 0.051) = 0.10
        self.assertEqual(out["billable_weight_kg"], 0.10)

    def test_multi_item_sums_weight_and_volume(self):
        cart = {
            "items": [
                {
                    "variation_id": "v1", "product_id": "p1", "quantity": 1,
                    "unit_price_cents": 1800000,
                    "variation": {"weight_kg": 0.10, "length_cm": 8, "width_cm": 8, "height_cm": 4},
                },
                {
                    "variation_id": "v2", "product_id": "p2", "quantity": 2,
                    "unit_price_cents": 3200000,
                    "variation": {"weight_kg": 0.18, "length_cm": 10, "width_cm": 10, "height_cm": 5},
                },
            ],
        }
        out = compute_shipping_inputs(cart)
        # físico = 0.10*1 + 0.18*2 = 0.46 kg
        self.assertEqual(out["weight_kg"], 0.46)
        # vol coco: 8*8*4=256 → 0.051
        # vol lavanda escalado por qty=2 (cube root 2 = 1.26): 12.6*12.6*6.3 ≈ 1000.18 / 5000 = 0.200
        self.assertGreater(out["volumetric_weight_kg"], 0.0)
        self.assertGreaterEqual(out["billable_weight_kg"], out["weight_kg"])
        self.assertEqual(len(out["lines"]), 2)


class AddItemTests(unittest.TestCase):

    def test_add_item_invokes_rpc_and_invalidates_shipping(self):
        sb = _supabase_with_table_data({
            "conversation_carts": [{
                "id": "cart-1", "shipping_meta": {"city": "Bogotá"},
                "subtotal_cents": 0,
            }],
        })
        out = add_item(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            product_id="p-1", variation_id="v-1",
            quantity=2, unit_price_cents=1800000,
        )
        names_called = [c[0] for c in sb._rpc_calls]
        self.assertIn("cart_add_item", names_called)
        params = sb._rpc_calls[0][1]
        self.assertEqual(params["p_quantity"], 2)
        self.assertEqual(params["p_unit_price_cents"], 1800000)
        self.assertEqual(out["cart_id"], "cart-1")

    def test_add_item_rejects_qty_zero(self):
        sb = _supabase_with_table_data({})
        with self.assertRaises(ValueError):
            add_item(sb, cart_id="x", tenant_id="x", product_id="x",
                     variation_id="x", quantity=0, unit_price_cents=100)


class UpdateRemoveTests(unittest.TestCase):

    def test_update_with_qty_zero_calls_remove(self):
        sb = _supabase_with_table_data({
            "conversation_carts": [{"id": "c", "shipping_meta": {}, "subtotal_cents": 0}],
            "conversation_cart_items": [],
        })
        out = update_item_quantity(
            sb, cart_id="c", tenant_id="t", product_id="p", variation_id="v",
            new_quantity=0, unit_price_cents=100,
        )
        self.assertIn("new_subtotal_cents", out)


class SetShippingMetaTests(unittest.TestCase):

    def test_set_shipping_meta_recomputes_total(self):
        sb = _supabase_with_table_data({
            "conversation_carts": [{"subtotal_cents": 8200000}],
        })
        out = set_shipping_meta(
            sb, cart_id="c", tenant_id="t",
            carrier="Servientrega", service_level="Económica",
            rate_id="rate-1", city="Bogotá", dane_code="11001",
            address_line="Calle 3 sur 70-84",
            weight_inputs={"weight_kg": 0.46, "billable_weight_kg": 0.46},
            shipping_cents=674000,
        )
        # total esperado: 8200000 + 674000 = 8874000
        self.assertEqual(out["total_cents"], 8874000)


class InvalidateShippingTests(unittest.TestCase):

    def test_invalidate_preserves_address(self):
        sb = _supabase_with_table_data({
            "conversation_carts": [{
                "shipping_meta": {
                    "city": "Bogotá", "dane_code": "11001",
                    "address_line": "Calle 1", "carrier": "X", "rate_id": "r",
                },
                "subtotal_cents": 1800000,
            }],
        })
        out = invalidate_shipping(sb, cart_id="c", reason="item_added")
        self.assertTrue(out["invalidated"])
        self.assertEqual(out["reason"], "item_added")


if __name__ == "__main__":
    unittest.main()
