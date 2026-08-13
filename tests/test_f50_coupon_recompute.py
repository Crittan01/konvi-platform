"""F50 — El descuento del cupón se recomputa en cada mutación del cart.

Bug (audit fullstack-review-2026-07-03, F50): `conversation_carts.discount_cents`
se materializaba al aplicar el cupón y quedaba CONGELADO. Mutaciones posteriores
recalculaban `total_cents` con el descuento viejo:

  · free_shipping: al elegir un carrier distinto al cotizado, el descuento seguía
    anclado al shipping viejo → se cobraba el diferencial (o se regalaba envío).
  · percent / fixed_amount: tras add/remove item, el descuento quedaba sobre el
    subtotal viejo (menos/más descuento del que corresponde).
  · min_subtotal: el cupón seguía aplicando aunque el cart bajara del mínimo al
    quitar ítems.

Fix: helper `_fresh_coupon_discount` invocado en set_shipping_meta,
invalidate_shipping y set_shipping_city — recomputa el valor con subtotal/shipping
vigentes y auto-revoca SOLO cuando el cart deja de calificar por su propio
contenido (min_subtotal_not_met). Ver docstring del helper para la política de
revocación (coherente con consume_redemption / ADR-0015 D5).
"""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.cart_tool import (  # noqa: E402
    invalidate_shipping,
    set_shipping_city,
    set_shipping_meta,
)

TENANT = "tenant-A"
CART = "cart-1"
COUPON = "coupon-1"


# ─── Fake Supabase (select / update; sin RPC — probamos mutaciones directas) ───

class _FakeQuery:
    def __init__(self, store, op="select", payload=None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters = []
        self._limit = None

    def select(self, cols="*"):
        return _FakeQuery(self._store, op="select")

    def update(self, payload):
        return _FakeQuery(self._store, op="update", payload=payload)

    def insert(self, payload):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    row.update(self._payload)
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"id-{len(self._store) + 1}")
            self._store.append(row)
            return SimpleNamespace(data=[row])
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self.tables = {
            "coupons": [],
            "coupon_redemptions": [],
            "conversation_carts": [],
        }

    def table(self, name):
        return _FakeQuery(self.tables[name])

    def rpc(self, *a, **k):  # no usado en estas rutas
        return SimpleNamespace(data=None, execute=lambda: SimpleNamespace(data=None))


def _seed(sb, *, subtotal, shipping, discount, coupon_type, discount_value,
          min_subtotal=0, with_redemption=True):
    sb.tables["coupons"].append({
        "id": COUPON, "tenant_id": TENANT, "code": "PROMO",
        "discount_type": coupon_type, "discount_value": discount_value,
        "min_subtotal_cents": min_subtotal, "max_redemptions": None,
        "redemptions_count": 0, "valid_from": None, "valid_until": None,
        "is_active": True,
    })
    sb.tables["conversation_carts"].append({
        "id": CART, "tenant_id": TENANT,
        "subtotal_cents": subtotal, "shipping_cents": shipping,
        "total_cents": subtotal + shipping - discount,
        "discount_cents": discount, "coupon_id": COUPON,
        "coupon_code": "PROMO", "shipping_meta": {},
    })
    if with_redemption:
        sb.tables["coupon_redemptions"].append({
            "id": "red-1", "tenant_id": TENANT, "cart_id": CART,
            "coupon_id": COUPON, "discount_applied_cents": discount,
            "status": "applied",
        })


def _cart(sb):
    return sb.tables["conversation_carts"][0]


class FreeShippingRecomputeTests(unittest.TestCase):
    def test_free_shipping_follows_new_carrier_cost(self):
        """Cupón envío gratis: elegir carrier más caro NO cobra el diferencial."""
        sb = _FakeSupabase()
        # Cupón free_shipping aplicado cuando el envío cotizado era 10.000.
        _seed(sb, subtotal=100000, shipping=10000, discount=10000,
              coupon_type="free_shipping", discount_value=0)
        # El cliente elige un carrier de 15.000.
        set_shipping_meta(sb, cart_id=CART, tenant_id=TENANT,
                          carrier="Servientrega", shipping_cents=15000)
        cart = _cart(sb)
        # El descuento sigue al shipping nuevo → envío realmente gratis.
        self.assertEqual(cart["discount_cents"], 15000)
        self.assertEqual(cart["total_cents"], 100000)  # subtotal + 15000 - 15000

    def test_free_shipping_reset_to_zero_on_city_change(self):
        """Cambio de ciudad resetea shipping=0 → descuento free_shipping = 0 hasta recotizar."""
        sb = _FakeSupabase()
        _seed(sb, subtotal=100000, shipping=12000, discount=12000,
              coupon_type="free_shipping", discount_value=0)
        set_shipping_city(sb, cart_id=CART, tenant_id=TENANT, new_city="Medellin")
        cart = _cart(sb)
        self.assertEqual(cart["discount_cents"], 0)
        self.assertEqual(cart["total_cents"], 100000)  # subtotal - 0
        self.assertTrue(cart["requires_requote"])


class PercentRecomputeTests(unittest.TestCase):
    def test_percent_scales_with_new_subtotal_on_item_change(self):
        """Cupón 10%: al cambiar subtotal (add item), el descuento escala."""
        sb = _FakeSupabase()
        # Descuento congelado en 10.000 (10% de 100.000); el cliente agregó ítems
        # y el subtotal ya subió a 250.000 (add_item actualiza subtotal antes de
        # llamar invalidate_shipping).
        _seed(sb, subtotal=250000, shipping=0, discount=10000,
              coupon_type="percent", discount_value=10)
        invalidate_shipping(sb, cart_id=CART, tenant_id=TENANT, reason="item_added")
        cart = _cart(sb)
        self.assertEqual(cart["discount_cents"], 25000)  # 10% de 250.000
        self.assertEqual(cart["total_cents"], 225000)


class MinSubtotalRevocationTests(unittest.TestCase):
    def test_coupon_auto_revoked_when_cart_drops_below_min(self):
        """Quitar ítems por debajo del mínimo → cupón se auto-revoca."""
        sb = _FakeSupabase()
        # Cupón 10% con mínimo 50.000. El cliente quitó ítems → subtotal 40.000.
        _seed(sb, subtotal=40000, shipping=0, discount=10000,
              coupon_type="percent", discount_value=10, min_subtotal=50000)
        invalidate_shipping(sb, cart_id=CART, tenant_id=TENANT, reason="item_removed")
        cart = _cart(sb)
        # Cupón limpiado del cart.
        self.assertIsNone(cart["coupon_id"])
        self.assertEqual(cart["discount_cents"], 0)
        self.assertEqual(cart["total_cents"], 40000)  # sin descuento
        # Redemption marcada revocada (audit trail).
        red = sb.tables["coupon_redemptions"][0]
        self.assertEqual(red["status"], "revoked")

    def test_coupon_survives_when_still_above_min(self):
        """Above min: no revoca, recomputa valor."""
        sb = _FakeSupabase()
        _seed(sb, subtotal=80000, shipping=0, discount=10000,
              coupon_type="percent", discount_value=10, min_subtotal=50000)
        invalidate_shipping(sb, cart_id=CART, tenant_id=TENANT, reason="item_removed")
        cart = _cart(sb)
        self.assertEqual(cart["coupon_id"], COUPON)
        self.assertEqual(cart["discount_cents"], 8000)  # 10% de 80.000
        self.assertEqual(cart["total_cents"], 72000)


class NoCouponTests(unittest.TestCase):
    def test_no_coupon_leaves_discount_zero(self):
        sb = _FakeSupabase()
        sb.tables["conversation_carts"].append({
            "id": CART, "tenant_id": TENANT, "subtotal_cents": 100000,
            "shipping_cents": 0, "total_cents": 100000, "discount_cents": 0,
            "coupon_id": None, "coupon_code": None, "shipping_meta": {},
        })
        set_shipping_meta(sb, cart_id=CART, tenant_id=TENANT,
                          carrier="Envia", shipping_cents=12000)
        cart = _cart(sb)
        self.assertEqual(cart["discount_cents"], 0)
        self.assertEqual(cart["total_cents"], 112000)


if __name__ == "__main__":
    unittest.main()
