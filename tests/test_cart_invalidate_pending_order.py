"""Tests del invariant `invalidate_pending_order_on_cart_change` (rev. 104,
ADR-0011).

Plan A.0.1 — cart-as-SoT: si la conversación tiene una orden
`pending_payment` activa al momento de mutar el cart (add_item /
update_item_quantity / remove_item), la orden se cancela + sus
`payments.pending` se marcan `voided`. El bot debe informar al cliente
que el link anterior ya no es válido.

Caso runtime motivador: cliente recibe link Wompi por $25.310 (1x Coco).
Después dice "agrégame 1 sérum 30ml" → cart pasa a 2 items / $63.000.
Sin invalidación: link viejo seguía vivo por $25.310 → si cliente lo
abría y pagaba, recibía productos por $63.000 pagando $25.310 → pérdida.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.cart_tool import (  # noqa: E402
    add_item,
    invalidate_pending_order_on_cart_change,
    remove_item,
)


def _build_supabase(
    *,
    cart_conversation_id: str | None = "conv-1",
    pending_orders: list[dict] | None = None,
    rpc_payload: dict | None = None,
):
    """Mock supabase route-by-table que soporta:
      • conversation_carts.select(conversation_id) → fila con cart_conversation_id
      • orders.select pending_payment → pending_orders
      • orders.update → ok
      • payments.update voided → captura voided count
      • rpc('cart_add_item') → rpc_payload (default minimal)
    """
    pending_orders = pending_orders or []
    rpc_payload = rpc_payload or {
        "cart_id": "cart-1", "new_version": 2,
        "subtotal_cents": 6300000, "total_cents": 6300000,
    }

    captured = {
        "orders_updated": [],     # list of order_ids cancelled
        "payments_voided": 0,
        "events_emitted": [],     # list of event_types
    }

    def _make_carts_chain():
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        if cart_conversation_id:
            chain.execute.return_value = MagicMock(
                data=[{"conversation_id": cart_conversation_id}],
            )
        else:
            chain.execute.return_value = MagicMock(data=[])
        # update también necesita devolver chain (para invalidate_shipping etc.)
        chain.update.return_value = chain
        return chain

    def _make_orders_chain():
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=pending_orders)
        # update path: capturar order_id desde el último .eq("id", X)
        update_chain = MagicMock()
        captured_id = {"v": None}

        def _eq_id(col, val):
            if col == "id":
                captured_id["v"] = val
            return update_chain

        update_chain.eq = _eq_id

        def _exec_update():
            if captured_id["v"]:
                captured["orders_updated"].append(captured_id["v"])
            return MagicMock(data=[{"id": captured_id["v"]}])

        update_chain.execute = _exec_update
        chain.update.return_value = update_chain
        return chain

    def _make_payments_chain():
        chain = MagicMock()
        update_chain = MagicMock()
        update_chain.eq.return_value = update_chain

        def _exec_update():
            captured["payments_voided"] += 1
            return MagicMock(data=[{"id": "pay-voided"}])

        update_chain.execute = _exec_update
        chain.update.return_value = update_chain
        # delete (remove_item lo usa para conversation_cart_items, pero
        # payments no debería recibir delete).
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        chain.select.return_value = chain
        return chain

    def _make_items_chain():
        # conversation_cart_items: delete + select para recálculo de subtotal
        chain = MagicMock()
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.select.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        return chain

    def _table(name):
        if name == "conversation_carts":
            return _make_carts_chain()
        if name == "orders":
            return _make_orders_chain()
        if name == "payments":
            return _make_payments_chain()
        if name == "conversation_cart_items":
            return _make_items_chain()
        if name == "cart_events":
            ch = MagicMock()
            ch.insert.return_value = ch
            ch.execute.return_value = MagicMock(data=[])

            def _capture_insert(payload):
                captured["events_emitted"].append(
                    payload.get("event_type") if isinstance(payload, dict) else None,
                )
                return ch

            ch.insert.side_effect = _capture_insert
            return ch
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.execute.return_value = MagicMock(data=[])
        return m

    sb = MagicMock()
    sb.table.side_effect = _table
    sb.rpc.return_value = MagicMock(execute=lambda: MagicMock(data=[rpc_payload]))
    sb._captured = captured
    return sb


class InvalidateHelperTests(unittest.TestCase):

    def test_returns_none_when_no_pending_payment_order(self):
        """Caso normal: cart sin orden activa → no hay nada que invalidar."""
        sb = _build_supabase(pending_orders=[])
        result = invalidate_pending_order_on_cart_change(
            sb, cart_id="cart-1", tenant_id="tenant-1", reason="item_added",
        )
        self.assertIsNone(result)
        self.assertEqual(sb._captured["orders_updated"], [])
        self.assertEqual(sb._captured["payments_voided"], 0)

    def test_returns_none_when_cart_not_found(self):
        """Cart fantasma: helper degrada limpio (no crash)."""
        sb = _build_supabase(cart_conversation_id=None)
        result = invalidate_pending_order_on_cart_change(
            sb, cart_id="cart-missing", tenant_id="tenant-1", reason="item_added",
        )
        self.assertIsNone(result)

    def test_cancels_order_and_voids_payments_when_active(self):
        """Caso runtime: orden pending_payment activa → cancela + voided."""
        sb = _build_supabase(
            pending_orders=[{
                "id": "order-active-12345678",
                "total_amount": 25310.0,
                "notes": "Pedido conversacional — Total: $25.310 COP",
            }],
        )
        result = invalidate_pending_order_on_cart_change(
            sb, cart_id="cart-1", tenant_id="tenant-1", reason="item_added",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["order_id"], "order-active-12345678")
        self.assertEqual(result["reason"], "item_added")
        self.assertEqual(result["voided_payment_count"], 1)
        # Verificó cancelación
        self.assertIn("order-active-12345678", sb._captured["orders_updated"])
        # Emitió cart_event
        self.assertIn(
            "order_invalidated_due_to_cart_change",
            sb._captured["events_emitted"],
        )

    def test_does_not_crash_if_voided_payments_fail(self):
        """Si payments.update falla, la orden ya está cancelada (lo más
        importante). Helper retorna info de cancelación con voided=0."""
        sb = _build_supabase(
            pending_orders=[{"id": "order-active", "total_amount": 25310.0, "notes": ""}],
        )

        # Sobrescribe payments.update.execute para que falle
        original_table = sb.table.side_effect

        def _table(name):
            if name == "payments":
                ch = MagicMock()
                upd = MagicMock()
                upd.eq.return_value = upd
                upd.execute.side_effect = RuntimeError("DB lost")
                ch.update.return_value = upd
                return ch
            return original_table(name)

        sb.table.side_effect = _table

        result = invalidate_pending_order_on_cart_change(
            sb, cart_id="cart-1", tenant_id="tenant-1", reason="item_added",
        )
        # Cancelación de orden sí completó; voided count refleja el fallo
        self.assertIsNotNone(result)
        self.assertEqual(result["voided_payment_count"], 0)


class AddItemInvalidationIntegrationTests(unittest.TestCase):

    def test_add_item_invalidates_pending_order(self):
        """add_item con orden pending_payment activa: invalidación se
        ejecuta y el flag `order_invalidated` aparece en el payload retornado
        para que el orchestrator informe al cliente."""
        sb = _build_supabase(
            pending_orders=[{
                "id": "order-active-12345678",
                "total_amount": 25310.0,
                "notes": "",
            }],
        )
        out = add_item(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            product_id="p-serum", variation_id="v-30ml",
            quantity=1, unit_price_cents=4500000,
        )
        self.assertIn("order_invalidated", out)
        self.assertEqual(out["order_invalidated"]["order_id"], "order-active-12345678")
        self.assertEqual(out["order_invalidated"]["reason"], "item_added")

    def test_add_item_no_invalidation_when_cart_clean(self):
        """add_item sin orden activa: payload retornado NO trae el flag."""
        sb = _build_supabase(pending_orders=[])
        out = add_item(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            product_id="p-coco", variation_id="v-60g",
            quantity=2, unit_price_cents=1800000,
        )
        self.assertNotIn("order_invalidated", out)


class RemoveItemInvalidationIntegrationTests(unittest.TestCase):

    def test_remove_item_invalidates_pending_order(self):
        """remove_item también dispara invalidación: cliente quita un
        producto del cart después de generar link → link queda con monto
        equivocado (más alto que el cart real)."""
        sb = _build_supabase(
            pending_orders=[{
                "id": "order-stale-rem",
                "total_amount": 25310.0,
                "notes": "",
            }],
        )
        out = remove_item(
            sb, cart_id="cart-1", tenant_id="tenant-1",
            variation_id="v-coco-60g",
        )
        self.assertIn("order_invalidated", out)
        self.assertEqual(out["order_invalidated"]["reason"], "item_removed")


if __name__ == "__main__":
    unittest.main()
