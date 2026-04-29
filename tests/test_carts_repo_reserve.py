"""Tests del wiring soft-reserve en CartsRepo.

Cubre:
- reserve_stock_for_cart con éxito → llama RPC por cada item.
- reserve_stock_for_cart con insufficient_stock → marca el variation_id
  en la lista insufficient sin cancelar los demás.
- consume_reservations_for_order itera sobre todas las activas.
- release_reservations_for_cart libera todas las activas.
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from persistence.carts_repo import CartsRepo  # noqa: E402


class _Q:
    """Chainable Supabase query mock."""
    def __init__(self, data=None):
        self._data = data
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def execute(self):
        return SimpleNamespace(data=self._data)


class _SBFake:
    def __init__(self):
        self.rpc_calls: list[tuple[str, dict]] = []
        self.rpc_responses: list = []  # respuestas o excepciones encoladas
        self.tables_data: dict[str, list] = {}

    def table(self, name: str):
        return _Q(self.tables_data.get(name) or [])

    def rpc(self, name: str, args: dict):
        self.rpc_calls.append((name, args))
        if self.rpc_responses:
            r = self.rpc_responses.pop(0)
            if isinstance(r, Exception):
                # Hacemos que execute() levante la excepción
                class _E:
                    def execute(self): raise r
                return _E()
            return _Q(r)
        return _Q([])


class ReserveStockTests(unittest.TestCase):
    def test_reserves_each_item_separately(self):
        sb = _SBFake()
        sb.rpc_responses = [
            [{"out_reservation_id": "res-1", "out_expires_at": "2026-05-02T00:35:00Z", "out_available_after": 4}],
            [{"out_reservation_id": "res-2", "out_expires_at": "2026-05-02T00:35:00Z", "out_available_after": 9}],
        ]
        repo = CartsRepo(sb)
        reservations, insufficient = repo.reserve_stock_for_cart(
            tenant_id="t1",
            cart_id="cart-1",
            conversation_id="conv-1",
            items=[
                {"variation_id": "var-A", "qty": 1},
                {"variation_id": "var-B", "qty": 1},
            ],
        )
        self.assertEqual(len(reservations), 2)
        self.assertEqual(insufficient, [])
        self.assertEqual(len(sb.rpc_calls), 2)
        self.assertEqual(sb.rpc_calls[0][0], "rpc_stock_reserve")
        self.assertEqual(sb.rpc_calls[0][1]["p_variation_id"], "var-A")
        self.assertEqual(sb.rpc_calls[1][1]["p_variation_id"], "var-B")
        self.assertEqual(reservations[0]["reservation_id"], "res-1")

    def test_insufficient_stock_marks_variation_continues_others(self):
        sb = _SBFake()
        sb.rpc_responses = [
            Exception("rpc_stock_reserve: insufficient_stock [P0001] available=0 requested=1"),
            [{"out_reservation_id": "res-2", "out_expires_at": "2026-05-02T00:35:00Z", "out_available_after": 4}],
        ]
        repo = CartsRepo(sb)
        reservations, insufficient = repo.reserve_stock_for_cart(
            tenant_id="t1",
            cart_id="cart-1",
            conversation_id="conv-1",
            items=[
                {"variation_id": "var-out", "qty": 1},
                {"variation_id": "var-ok", "qty": 1},
            ],
        )
        self.assertEqual(insufficient, ["var-out"])
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]["variation_id"], "var-ok")

    def test_invalid_qty_skipped(self):
        sb = _SBFake()
        repo = CartsRepo(sb)
        reservations, insufficient = repo.reserve_stock_for_cart(
            tenant_id="t1", cart_id="cart-1", conversation_id="conv-1",
            items=[{"variation_id": "var-A", "qty": 0}],
        )
        self.assertEqual(reservations, [])
        self.assertEqual(insufficient, [])
        self.assertEqual(len(sb.rpc_calls), 0)


class ConsumeReservationsTests(unittest.TestCase):
    def test_consumes_all_active(self):
        sb = _SBFake()
        sb.tables_data["stock_reservations"] = [
            {"id": "r1"}, {"id": "r2"},
        ]
        sb.rpc_responses = [[], []]
        repo = CartsRepo(sb)
        n = repo.consume_reservations_for_order(cart_id="cart-1", order_id="ord-1")
        self.assertEqual(n, 2)
        self.assertEqual(len(sb.rpc_calls), 2)
        self.assertEqual(sb.rpc_calls[0][0], "rpc_stock_reservation_consume")
        self.assertEqual(sb.rpc_calls[0][1]["p_order_id"], "ord-1")


class ReleaseReservationsTests(unittest.TestCase):
    def test_releases_all_active(self):
        sb = _SBFake()
        sb.tables_data["stock_reservations"] = [{"id": "r1"}, {"id": "r2"}]
        sb.rpc_responses = [[], []]
        repo = CartsRepo(sb)
        n = repo.release_reservations_for_cart(cart_id="cart-1")
        self.assertEqual(n, 2)
        self.assertEqual(sb.rpc_calls[0][0], "rpc_stock_reservation_release")


if __name__ == "__main__":
    unittest.main()
