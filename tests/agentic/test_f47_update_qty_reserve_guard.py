"""F47 — UpdateCartItemQtyTool aborta si reserve() retorna ok=False (sin lanzar).

reserve() lanza InsufficientStock SOLO para falta de stock; otros fallos
(VARIATION_NOT_FOUND / INTERNAL) retornan ReservationResult(ok=False) SIN excepción.
Antes UpdateCartItemQtyTool descartaba ese retorno → actualizaba la qty del cart sin
reserva válida (riesgo de oversell). El gap ya estaba cerrado en AddToCartTool; este
test fija el mismo guard para UpdateCartItemQtyTool.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_CART = {
    "id": "cart-1",
    "items": [{
        "id": "ci-000001", "variation_id": "var-1", "product_id": "prod-1",
        "quantity": 1, "unit_price_cents": 5000,
    }],
}


class F47ReserveGuardTests(unittest.TestCase):
    def setUp(self):
        import agentic.tools.cart  # noqa: F401 — registra el tool
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext
        self.tool = get_tool("update_cart_item_quantity")
        self.ctx = ToolContext(
            tenant_id="t-1", conversation_id="c-1", contact_id="ct-1",
            supabase=MagicMock(), extras={}, logger=MagicMock(),
        )

    def _patches(self, reserve_result, update_mock):
        from lib.stock_reservation import ReservationResult  # noqa: F401
        return [
            patch("tools.cart_tool.get_cart_with_items", return_value=_CART),
            patch("tools.cart_tool.update_item_quantity", update_mock),
            patch("lib.stock_reservation.release_by_cart", return_value=None),
            patch("lib.stock_reservation.reserve", return_value=reserve_result),
        ]

    def test_reserve_ok_false_aborta_sin_tocar_cart(self):
        from lib.stock_reservation import ReservationResult
        args = self.tool.args_schema(cart_item_id="ci-000001", new_quantity=3)
        m_update = MagicMock()
        res = ReservationResult(ok=False, error_code="VARIATION_NOT_FOUND")
        patches = self._patches(res, m_update)
        for p in patches:
            p.start()
        try:
            r = _run(self.tool.execute(args, self.ctx))
        finally:
            for p in patches:
                p.stop()
        self.assertFalse(r.success)
        self.assertEqual(r.data["code"], "VARIATION_NOT_FOUND")
        m_update.assert_not_called()  # cart NO se actualiza → sin oversell

    def test_reserve_ok_true_procede_a_update(self):
        from lib.stock_reservation import ReservationResult
        args = self.tool.args_schema(cart_item_id="ci-000001", new_quantity=2)
        m_update = MagicMock(return_value={"ok": True})
        res = ReservationResult(ok=True, reservation_id="r-1")
        patches = self._patches(res, m_update)
        for p in patches:
            p.start()
        try:
            _run(self.tool.execute(args, self.ctx))
        finally:
            for p in patches:
                p.stop()
        m_update.assert_called_once()  # reserva válida → sí actualiza


if __name__ == "__main__":
    unittest.main()
