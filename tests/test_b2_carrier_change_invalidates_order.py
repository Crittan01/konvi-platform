"""B2 (auditoría money-path 2026-08-21) — cambio de carrier / re-cotización
invalida la orden pending_payment.

Antes: las mutaciones de items invalidaban la orden pendiente (ADR-0011) pero
`set_shipping_meta` / `select_carrier_for_cart` NO → el cliente podía pagar un
link cuyo total ya no reflejaba el envío elegido.

Cubre (services/ai-orchestrator/tools/cart_tool.py + agentic/legacy_adapters/cart.py):
  • set_shipping_meta con orden pending_payment → cancela orden + voided
    payments, ANTES de mutar el cart; snapshot incluye order_invalidated.
  • set_shipping_meta SIN orden pendiente → no-op seguro (cliente aún armando
    el pedido); el update del cart ocurre igual.
  • Re-cotización (shipping_cents=0) también invalida (reason shipping_quoted).
  • select_carrier_for_cart propaga order_invalidated + notice al LLM.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.cart_tool import set_shipping_meta  # noqa: E402


class _Chain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table, self.cols = ctrl, table, ""

    def select(self, cols="*", *a, **k):
        self.cols = cols
        return self

    def update(self, data, *a, **k):
        self.ctrl.updates.append((self.table, data))
        return self

    def insert(self, rows, *a, **k):
        self.ctrl.inserts.append((self.table, rows))
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.ctrl._exec(self.table, self.cols))


class _Ctrl:
    def __init__(self, *, pending_orders=None, cart_row=None):
        self.pending_orders = pending_orders or []
        self.cart_row = cart_row or {
            "subtotal_cents": 200_000, "shipping_meta": {},
            "discount_cents": 0, "coupon_id": None,
        }
        self.updates = []
        self.inserts = []

    def table(self, name):
        return _Chain(self, name)

    def _exec(self, table, cols):
        if table == "conversation_carts":
            if cols == "conversation_id":  # lookup del invalidador
                return [{"conversation_id": "conv-1"}]
            return [self.cart_row]  # cur: subtotal/shipping_meta/discount/coupon
        if table == "orders":
            return self.pending_orders
        return []


_PENDING = [{"id": "order-pend-1", "total_amount": 2100.0, "notes": "x"}]


class SetShippingMetaInvalidationTests(unittest.TestCase):
    def test_carrier_change_invalidates_pending_order(self):
        sb = _Ctrl(pending_orders=list(_PENDING))
        snapshot = set_shipping_meta(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            carrier="SERVIENTREGA", service_level="premium",
            rate_id="rate-9", shipping_cents=9_000,
        )
        order_updates = [u for u in sb.updates if u[0] == "orders"]
        pay_updates = [u for u in sb.updates if u[0] == "payments"]
        self.assertTrue(order_updates, "la orden pendiente debió cancelarse")
        self.assertEqual(order_updates[0][1]["status"], "cancelled")
        self.assertIn("carrier_selected", order_updates[0][1]["notes"])
        self.assertTrue(pay_updates, "los payments pendientes debieron quedar voided")
        self.assertEqual(pay_updates[0][1]["status"], "voided")
        # Snapshot informa la invalidación para que el caller avise al cliente.
        self.assertEqual(snapshot["order_invalidated"]["order_id"], "order-pend-1")
        # Y la mutación del cart ocurrió con los totales nuevos.
        cart_updates = [u for u in sb.updates if u[0] == "conversation_carts"]
        self.assertTrue(cart_updates)
        self.assertEqual(cart_updates[0][1]["shipping_cents"], 9_000)
        self.assertEqual(snapshot["total_cents"], 209_000)

    def test_no_pending_order_is_safe_noop(self):
        """Cliente cambia de carrier ANTES de tener link → no-op, mutación normal."""
        sb = _Ctrl(pending_orders=[])
        snapshot = set_shipping_meta(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            carrier="COORDINADORA", shipping_cents=7_500,
        )
        self.assertNotIn("order_invalidated", snapshot)
        self.assertFalse([u for u in sb.updates if u[0] == "orders"])
        cart_updates = [u for u in sb.updates if u[0] == "conversation_carts"]
        self.assertTrue(cart_updates, "el cart sí se actualizó")
        self.assertEqual(snapshot["total_cents"], 207_500)

    def test_requote_without_selection_also_invalidates(self):
        """Re-cotizar (shipping_cents=0) con link emitido también invalida."""
        sb = _Ctrl(
            pending_orders=list(_PENDING),
            cart_row={
                "subtotal_cents": 200_000,
                "shipping_meta": {"carrier": "SERVIENTREGA", "shipping_cents": 9_000},
                "discount_cents": 0, "coupon_id": None,
            },
        )
        snapshot = set_shipping_meta(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            carrier="", shipping_cents=0,
        )
        order_updates = [u for u in sb.updates if u[0] == "orders"]
        self.assertTrue(order_updates)
        self.assertIn("shipping_quoted", order_updates[0][1]["notes"])
        self.assertIn("order_invalidated", snapshot)

    def test_identical_reselection_does_not_invalidate(self):
        """Re-elegir el MISMO carrier al MISMO precio no cambia el total → la
        orden pendiente sobrevive (invalidar aquí sería romper el link de gratis)."""
        sb = _Ctrl(
            pending_orders=list(_PENDING),
            cart_row={
                "subtotal_cents": 200_000,
                "shipping_meta": {"carrier": "SERVIENTREGA", "shipping_cents": 9_000},
                "discount_cents": 0, "coupon_id": None,
            },
        )
        snapshot = set_shipping_meta(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            carrier="SERVIENTREGA", service_level="premium",
            rate_id="rate-9", shipping_cents=9_000,
        )
        self.assertNotIn("order_invalidated", snapshot)
        self.assertFalse([u for u in sb.updates if u[0] == "orders"])
        cart_updates = [u for u in sb.updates if u[0] == "conversation_carts"]
        self.assertTrue(cart_updates, "la mutación del cart ocurre igual")


class SelectCarrierAdapterPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_propagates_order_invalidated_notice(self):
        from agentic.legacy_adapters.cart import select_carrier_for_cart

        invalidated = {"order_id": "order-pend-1", "reason": "carrier_selected"}
        fake_snapshot = {
            "id": "cart-1", "shipping_cents": 9_000, "subtotal_cents": 200_000,
            "total_cents": 209_000, "shipping_meta": {}, "requires_requote": False,
            "order_invalidated": invalidated,
        }
        with patch("tools.cart_tool.get_cart_with_items",
                   return_value={"id": "cart-1", "items": [{}]}), \
             patch("tools.cart_tool.set_shipping_meta", return_value=fake_snapshot):
            result = await select_carrier_for_cart(
                MagicMock(), conversation_id="conv-1", tenant_id="tenant-1",
                rate_id="rate-9",
                rate_data={"carrier": "SERVIENTREGA", "service_level": "premium",
                           "price_cents": 9_000},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["order_invalidated"]["order_id"], "order-pend-1")
        self.assertIn("link de pago anterior", result["notice"])

    async def test_adapter_sin_invalidacion_no_agrega_notice(self):
        from agentic.legacy_adapters.cart import select_carrier_for_cart

        fake_snapshot = {
            "id": "cart-1", "shipping_cents": 9_000, "subtotal_cents": 200_000,
            "total_cents": 209_000, "shipping_meta": {}, "requires_requote": False,
        }
        with patch("tools.cart_tool.get_cart_with_items",
                   return_value={"id": "cart-1", "items": [{}]}), \
             patch("tools.cart_tool.set_shipping_meta", return_value=fake_snapshot):
            result = await select_carrier_for_cart(
                MagicMock(), conversation_id="conv-1", tenant_id="tenant-1",
                rate_id="rate-9",
                rate_data={"carrier": "SERVIENTREGA", "price_cents": 9_000},
            )
        self.assertTrue(result["ok"])
        self.assertNotIn("order_invalidated", result)
        self.assertNotIn("notice", result)


if __name__ == "__main__":
    unittest.main()
