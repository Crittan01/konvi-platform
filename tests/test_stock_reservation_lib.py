"""Tests del lib stock_reservation (wrapper sobre RPCs DB).

Cubre:
  • reserve() success → ReservationResult(ok=True).
  • reserve() insufficient → raise InsufficientStock.
  • reserve() variation_not_found → ReservationResult(ok=False, code).
  • release_by_id() idempotente.
  • release_by_cart() retorna count.
  • consume_by_cart() retorna count.
  • extend_by_cart() retorna count.
  • available_stock() retorna int.
  • cleanup_expired() retorna count.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from lib import stock_reservation as sr


def _mock_supabase_rpc(rpc_responses: dict, table_responses: dict | None = None):
    """Construye mock supabase con .rpc().execute() retornando data segun key."""
    sb = MagicMock()
    def _rpc(name, params=None):
        chain = MagicMock()
        if name in rpc_responses:
            response = rpc_responses[name]
            if isinstance(response, Exception):
                chain.execute.side_effect = response
            else:
                chain.execute.return_value = MagicMock(data=response)
        else:
            chain.execute.return_value = MagicMock(data=None)
        return chain
    sb.rpc.side_effect = _rpc

    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        data = (table_responses or {}).get(name, [])
        chain.execute.return_value = MagicMock(data=data)
        return chain
    sb.table.side_effect = _table
    return sb


class ReserveTests(unittest.TestCase):
    def test_reserve_success_returns_id(self):
        sb = _mock_supabase_rpc({
            "rpc_stock_reserve": [{
                "out_reservation_id": "res-1",
                "out_expires_at": "2026-05-28T12:00:00+00:00",
                "out_available_after": 4,
            }],
        })
        result = sr.reserve(
            sb, tenant_id="t1", variation_id="v1", qty=2,
            cart_id="c1", conversation_id="conv1",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reservation_id, "res-1")
        self.assertEqual(result.available_after, 4)

    def test_reserve_insufficient_stock_raises(self):
        sb = _mock_supabase_rpc({
            "rpc_stock_reserve": Exception(
                "rpc_stock_reserve: insufficient_stock - DETAIL: available=2 requested=5 P0001"
            ),
            # available_stock fallback debe poder ser invocado
            "fn_variation_available_stock": 2,
        })
        with self.assertRaises(sr.InsufficientStock) as ctx:
            sr.reserve(
                sb, tenant_id="t1", variation_id="v1", qty=5,
                cart_id="c1",
            )
        self.assertEqual(ctx.exception.requested, 5)
        self.assertEqual(ctx.exception.variation_id, "v1")

    def test_reserve_variation_not_found(self):
        sb = _mock_supabase_rpc({
            "rpc_stock_reserve": Exception(
                "rpc_stock_reserve: variation_not_found"
            ),
        })
        result = sr.reserve(
            sb, tenant_id="t1", variation_id="vnonexistent", qty=1,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "VARIATION_NOT_FOUND")


class ReleaseTests(unittest.TestCase):
    def test_release_by_id_returns_true(self):
        sb = _mock_supabase_rpc({"rpc_stock_reservation_release": None})
        self.assertTrue(sr.release_by_id(sb, reservation_id="res-1"))

    def test_release_by_id_failure_returns_false(self):
        sb = _mock_supabase_rpc({
            "rpc_stock_reservation_release": Exception("DB down"),
        })
        self.assertFalse(sr.release_by_id(sb, reservation_id="res-1"))

    def test_release_by_cart_counts_releases(self):
        sb = _mock_supabase_rpc(
            {"rpc_stock_reservation_release": None},
            table_responses={
                "stock_reservations": [
                    {"id": "r1"}, {"id": "r2"}, {"id": "r3"},
                ],
            },
        )
        count = sr.release_by_cart(sb, tenant_id="t1", cart_id="c1")
        self.assertEqual(count, 3)


class ConsumeTests(unittest.TestCase):
    def test_consume_by_cart_counts(self):
        sb = _mock_supabase_rpc(
            {"rpc_stock_reservation_consume": None},
            table_responses={"stock_reservations": [{"id": "r1"}, {"id": "r2"}]},
        )
        count = sr.consume_by_cart(
            sb, tenant_id="t1", cart_id="c1", order_id="ord1",
        )
        self.assertEqual(count, 2)


class ExtendTests(unittest.TestCase):
    def test_extend_by_cart_counts(self):
        sb = _mock_supabase_rpc(
            {"rpc_stock_reservation_extend": "2026-05-28T13:00:00+00:00"},
            table_responses={"stock_reservations": [{"id": "r1"}, {"id": "r2"}]},
        )
        count = sr.extend_by_cart(sb, tenant_id="t1", cart_id="c1")
        self.assertEqual(count, 2)


class AvailableStockTests(unittest.TestCase):
    def test_available_stock_returns_int(self):
        sb = _mock_supabase_rpc({"fn_variation_available_stock": 7})
        self.assertEqual(sr.available_stock(sb, variation_id="v1"), 7)

    def test_available_stock_dict_response(self):
        sb = _mock_supabase_rpc({"fn_variation_available_stock": {"available": 3}})
        self.assertEqual(sr.available_stock(sb, variation_id="v1"), 3)

    def test_available_stock_list_response(self):
        sb = _mock_supabase_rpc({"fn_variation_available_stock": [5]})
        self.assertEqual(sr.available_stock(sb, variation_id="v1"), 5)


class CleanupTests(unittest.TestCase):
    def test_cleanup_expired_returns_count(self):
        sb = _mock_supabase_rpc({"fn_expire_stock_reservations": 4})
        self.assertEqual(sr.cleanup_expired(sb), 4)


if __name__ == "__main__":
    unittest.main()
