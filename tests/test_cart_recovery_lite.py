"""Tests F7-lite — cart recovery reactivo (rev. 70).

Cubre:
- Tokens léxicos "carrito"/"retomar"/etc. activan lazy mode.
- _cart_recovery_enabled() respeta kill switch.
- _cart_recovery_lookback_days() clamping.
- _load_cart_recovery_block:
    * carrito reciente con stock OK → bloque generado.
    * stock=0 en alguna variante → marca "SIN STOCK", excluye del total.
    * precio cambió → marca diff y usa precio actual.
    * sin order_items → vacío.
    * todo SIN STOCK → vacío (no inyecta ruido).
    * lookback excedido → no aparece (lo cubre el filtro DB; lo simulamos
      con orders_cancelled vacío y verificamos que el block es "").
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _cart_recovery_enabled,
    _cart_recovery_lookback_days,
    _customer_context_should_load,
    _load_cart_recovery_block,
    _load_customer_context_block,
)


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class _FakeQuery:
    """Stub de query chain de supabase-py.

    Captura filtros y devuelve data según la tabla y `status` filtrado.
    """

    def __init__(self, sb, table_name: str):
        self._sb = sb
        self._table = table_name
        self._filters: dict = {}

    def select(self, *a, **kw):
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def in_(self, key, value):
        self._filters[(key, "in")] = tuple(value)
        return self

    def gte(self, key, value):
        self._filters[(key, "gte")] = value
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def execute(self):
        if self._table == "orders":
            status = self._filters.get("status")
            if status == "cancelled":
                data = self._sb.cart_orders
            else:
                data = self._sb.active_orders
        elif self._table == "claims":
            data = self._sb.claims
        elif self._table == "product_variations":
            data = self._sb.variants
        else:
            data = []
        m = MagicMock()
        m.data = data
        return m


class FakeSupabase:
    def __init__(self, *, cart_orders=None, variants=None, active_orders=None, claims=None):
        self.cart_orders = cart_orders or []
        self.variants = variants or []
        self.active_orders = active_orders or []
        self.claims = claims or []
        self.tables_called: list[str] = []

    def table(self, name: str):
        self.tables_called.append(name)
        return _FakeQuery(self, name)


class CartRecoveryEnvTests(unittest.TestCase):
    def setUp(self):
        self._backup = {
            "CART_RECOVERY_ENABLED": os.environ.get("CART_RECOVERY_ENABLED"),
            "CART_RECOVERY_LOOKBACK_DAYS": os.environ.get("CART_RECOVERY_LOOKBACK_DAYS"),
        }

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_enabled_default_true(self):
        os.environ.pop("CART_RECOVERY_ENABLED", None)
        self.assertTrue(_cart_recovery_enabled())

    def test_enabled_kill_switch(self):
        os.environ["CART_RECOVERY_ENABLED"] = "false"
        self.assertFalse(_cart_recovery_enabled())

    def test_lookback_default_7(self):
        os.environ.pop("CART_RECOVERY_LOOKBACK_DAYS", None)
        self.assertEqual(_cart_recovery_lookback_days(), 7)

    def test_lookback_clamped_min(self):
        os.environ["CART_RECOVERY_LOOKBACK_DAYS"] = "0"
        self.assertEqual(_cart_recovery_lookback_days(), 1)

    def test_lookback_clamped_max(self):
        os.environ["CART_RECOVERY_LOOKBACK_DAYS"] = "9999"
        self.assertEqual(_cart_recovery_lookback_days(), 60)

    def test_lookback_invalid_falls_back_to_default(self):
        os.environ["CART_RECOVERY_LOOKBACK_DAYS"] = "abc"
        self.assertEqual(_cart_recovery_lookback_days(), 7)


class CustomerContextLazyTokensCartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._backup = {
            "CUSTOMER_CONTEXT_ENABLED": os.environ.get("CUSTOMER_CONTEXT_ENABLED"),
            "CUSTOMER_CONTEXT_MODE": os.environ.get("CUSTOMER_CONTEXT_MODE"),
        }
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_carrito_token_activates_lazy(self):
        for query in [
            "oye, ¿qué tenía en mi carrito?",
            "quiero retomar el de antes",
            "el carrito anterior",
            "lo que tenía pendiente",
            "quiero pagar",
        ]:
            self.assertTrue(
                _customer_context_should_load(query),
                f"esperaba True para: {query!r}",
            )


class LoadCartRecoveryBlockTests(unittest.TestCase):
    def setUp(self):
        self._backup = {
            "CART_RECOVERY_ENABLED": os.environ.get("CART_RECOVERY_ENABLED"),
            "CART_RECOVERY_LOOKBACK_DAYS": os.environ.get("CART_RECOVERY_LOOKBACK_DAYS"),
        }
        os.environ["CART_RECOVERY_ENABLED"] = "true"
        os.environ["CART_RECOVERY_LOOKBACK_DAYS"] = "7"

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _cart(self, items, days_ago: int = 2):
        return [{
            "id": "order-1",
            "status": "cancelled",
            "total_amount": "0",
            "created_at": _iso_days_ago(days_ago),
            "order_items": items,
        }]

    def test_kill_switch_off_returns_empty(self):
        os.environ["CART_RECOVERY_ENABLED"] = "false"
        sb = FakeSupabase(cart_orders=self._cart([
            {"title": "Camiseta", "unit_price": 30000, "quantity": 1, "variation_id": "v1"}
        ]), variants=[{"id": "v1", "stock_quantity": 5, "price": 30000}])
        result = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertEqual(result, "")

    def test_no_cart_returns_empty(self):
        sb = FakeSupabase(cart_orders=[], variants=[])
        result = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertEqual(result, "")

    def test_cart_with_stock_ok_renders_block(self):
        sb = FakeSupabase(
            cart_orders=self._cart([
                {"title": "Camiseta Negra M", "unit_price": 30000, "quantity": 2, "variation_id": "v1"},
                {"title": "Pantalón Beige 30", "unit_price": 85000, "quantity": 1, "variation_id": "v2"},
            ], days_ago=2),
            variants=[
                {"id": "v1", "stock_quantity": 10, "price": 30000},
                {"id": "v2", "stock_quantity": 4, "price": 85000},
            ],
        )
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertIn("CARRITO PREVIO", block)
        self.assertIn("hace 2 días", block)
        self.assertIn("Camiseta Negra M", block)
        self.assertIn("Pantalón Beige 30", block)
        self.assertIn("disponible", block)
        # Total recalculado = 2*30k + 1*85k = 145k (formato Colombia: punto miles)
        self.assertIn("$145.000", block)
        self.assertIn("INSTRUCCIÓN", block)

    def test_price_changed_marks_diff_and_uses_current_price(self):
        sb = FakeSupabase(
            cart_orders=self._cart([
                {"title": "Camiseta", "unit_price": 30000, "quantity": 2, "variation_id": "v1"},
            ]),
            variants=[
                {"id": "v1", "stock_quantity": 10, "price": 35000},
            ],
        )
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertIn("precio anterior $30.000", block)
        self.assertIn("AHORA $35.000", block)
        self.assertIn("precio cambió", block)
        # Total recalculado = 2 * 35k = 70k
        self.assertIn("$70.000", block)

    def test_stock_zero_marks_sin_stock_excludes_from_total(self):
        sb = FakeSupabase(
            cart_orders=self._cart([
                {"title": "Camiseta", "unit_price": 30000, "quantity": 2, "variation_id": "v1"},
                {"title": "Gorra", "unit_price": 20000, "quantity": 1, "variation_id": "v2"},
            ]),
            variants=[
                {"id": "v1", "stock_quantity": 5, "price": 30000},
                {"id": "v2", "stock_quantity": 0, "price": 20000},
            ],
        )
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertIn("Gorra", block)
        self.assertIn("SIN STOCK", block)
        # Solo la camiseta entra al total: 2 * 30k = 60k (Gorra excluida)
        self.assertIn("$60.000", block)
        self.assertNotIn("$80.000", block)

    def test_all_items_out_of_stock_returns_empty(self):
        sb = FakeSupabase(
            cart_orders=self._cart([
                {"title": "Camiseta", "unit_price": 30000, "quantity": 2, "variation_id": "v1"},
            ]),
            variants=[
                {"id": "v1", "stock_quantity": 0, "price": 30000},
            ],
        )
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertEqual(block, "")

    def test_variant_removed_marks_no_disponible(self):
        sb = FakeSupabase(
            cart_orders=self._cart([
                {"title": "Camiseta", "unit_price": 30000, "quantity": 1, "variation_id": "v1"},
                {"title": "Pantalon", "unit_price": 85000, "quantity": 1, "variation_id": "v2"},
            ]),
            variants=[
                {"id": "v2", "stock_quantity": 5, "price": 85000},  # v1 removed
            ],
        )
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertIn("variante removida", block)
        self.assertIn("Pantalon", block)
        self.assertIn("$85.000", block)

    def test_empty_order_items_returns_empty(self):
        sb = FakeSupabase(cart_orders=self._cart([]))
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertEqual(block, "")

    def test_supabase_error_returns_empty(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("DB down")
        block = _load_cart_recovery_block(sb, "tenant-1", "contact-1")
        self.assertEqual(block, "")


class LoadCustomerContextBlockIntegrationTests(unittest.TestCase):
    """Verifica que el bloque carrito previo se inyecta junto al CONTEXTO DEL CLIENTE
    cuando hay tanto pedidos activos como carrito recuperable."""

    def setUp(self):
        self._backup = {
            "CUSTOMER_CONTEXT_ENABLED": os.environ.get("CUSTOMER_CONTEXT_ENABLED"),
            "CUSTOMER_CONTEXT_MODE": os.environ.get("CUSTOMER_CONTEXT_MODE"),
            "CART_RECOVERY_ENABLED": os.environ.get("CART_RECOVERY_ENABLED"),
            "CART_RECOVERY_LOOKBACK_DAYS": os.environ.get("CART_RECOVERY_LOOKBACK_DAYS"),
        }
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"
        os.environ["CART_RECOVERY_ENABLED"] = "true"
        os.environ["CART_RECOVERY_LOOKBACK_DAYS"] = "7"

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_only_cart_recovery_inyectado_sin_orders_ni_claims(self):
        sb = FakeSupabase(
            active_orders=[],
            claims=[],
            cart_orders=[{
                "id": "cart-1",
                "status": "cancelled",
                "created_at": _iso_days_ago(1),
                "order_items": [
                    {"title": "Camiseta", "unit_price": 30000, "quantity": 1, "variation_id": "v1"},
                ],
            }],
            variants=[{"id": "v1", "stock_quantity": 5, "price": 30000}],
        )
        result = _load_customer_context_block(
            sb, "tenant-1", "contact-1", "Andrés", query_text="oye, mi carrito"
        )
        self.assertIn("CARRITO PREVIO", result)
        # Rev. 103 — el header "CONTEXTO DEL CLIENTE" siempre se inyecta
        # cuando hay AL MENOS algo (cart-recovery cuenta).
        self.assertIn("CONTEXTO DEL CLIENTE", result)

    def test_cart_y_pedidos_activos_coexisten(self):
        sb = FakeSupabase(
            active_orders=[{
                "id": "abc12345",
                "status": "shipped",
                "total_amount": 50000,
                "created_at": _iso_days_ago(0),
            }],
            claims=[],
            cart_orders=[{
                "id": "cart-1",
                "status": "cancelled",
                "created_at": _iso_days_ago(1),
                "order_items": [
                    {"title": "Camiseta", "unit_price": 30000, "quantity": 1, "variation_id": "v1"},
                ],
            }],
            variants=[{"id": "v1", "stock_quantity": 5, "price": 30000}],
        )
        result = _load_customer_context_block(
            sb, "tenant-1", "contact-1", "Andrés", query_text="¿dónde está mi pedido y mi carrito?"
        )
        self.assertIn("CONTEXTO DEL CLIENTE", result)
        self.assertIn("CARRITO PREVIO", result)
        self.assertIn("ABC12345", result)


if __name__ == "__main__":
    unittest.main()
