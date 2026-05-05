"""
Tests R-01: Liberación de pedidos pending_payment expirados.
Verifica que el worker cancela pedidos sin pago después del TTL,
sin afectar pedidos recientes ni los ya confirmados.

Rev. 104 — el cron consulta `payments` para preservar órdenes con un
intent de pago activo (bucket b de payment_link_tool). Si hay
`payments.pending` reciente (≤ TTL min) → no cancelar (ADR-0011).
"""
import os
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from worker import OrchestratorWorker, PENDING_PAYMENT_TTL_MINUTES


def _make_worker():
    with patch("worker.create_client") as mock_client:
        mock_client.return_value = MagicMock()
        w = OrchestratorWorker()
    return w


def _stub_supabase_for_release(
    *,
    stale_orders: list[dict],
    fresh_payments_by_order: dict[str, list[dict]] | None = None,
):
    """Construye un supabase mock route-by-table:

      table("orders").select(...).eq(...).lt(...).limit(...).execute() →
        data=stale_orders
      table("orders").update(...).eq(...).eq(...).execute() →
        data=[{"id": ...}] (cancelación exitosa)
      table("payments").select(...).eq(...).eq(...).gte(...).limit(...).execute() →
        data=fresh_payments_by_order.get(order_id, [])
    """
    fresh = fresh_payments_by_order or {}
    update_calls: list[str] = []

    def _make_orders_chain():
        select_chain = MagicMock()
        select_chain.eq.return_value = select_chain
        select_chain.lt.return_value = select_chain
        select_chain.limit.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=stale_orders)

        update_chain = MagicMock()

        def _eq_then_eq(*args, **kwargs):
            second = MagicMock()

            def _exec_capture():
                # Captura el order_id del primer .eq()
                if update_chain._captured_id is not None:
                    update_calls.append(update_chain._captured_id)
                return MagicMock(data=[{"id": update_chain._captured_id}])

            second.execute = _exec_capture
            return second

        update_chain._captured_id = None

        def _capture_eq(col, val):
            update_chain._captured_id = val
            return MagicMock(eq=_eq_then_eq)

        update_chain.eq = _capture_eq

        orders_table = MagicMock()
        orders_table.select.return_value = select_chain
        orders_table.update.return_value = update_chain
        return orders_table

    def _make_payments_chain():
        select_chain = MagicMock()

        captured = {"order_id": None}

        def _eq_capture(col, val):
            if col == "order_id":
                captured["order_id"] = val
            return select_chain

        select_chain.eq = _eq_capture
        select_chain.gte.return_value = select_chain
        select_chain.limit.return_value = select_chain
        select_chain.execute = lambda: MagicMock(
            data=fresh.get(captured["order_id"], [])
        )

        payments_table = MagicMock()
        payments_table.select.return_value = select_chain
        return payments_table

    def _table(name):
        if name == "orders":
            return _make_orders_chain()
        if name == "payments":
            return _make_payments_chain()
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table
    sb._update_calls = update_calls
    return sb


class PendingPaymentReleaseTests(unittest.IsolatedAsyncioTestCase):

    async def test_cancels_stale_pending_payment_orders(self):
        """Pedidos en pending_payment más viejos del TTL y SIN payment
        fresco deben cancelarse."""
        worker = _make_worker()
        worker._last_release_at = 0.0

        worker.supabase = _stub_supabase_for_release(
            stale_orders=[
                {"id": "order-1", "tenant_id": "tenant-1"},
                {"id": "order-2", "tenant_id": "tenant-1"},
            ],
            fresh_payments_by_order={},  # sin payment fresco
        )

        await worker._release_expired_pending_payment_orders()

        self.assertEqual(worker._metrics["expired_orders_cancelled"], 2)
        self.assertEqual(set(worker.supabase._update_calls), {"order-1", "order-2"})

    async def test_skips_cancellation_when_payment_recent(self):
        """Bucket (b) de payment_link_tool: si el cliente regeneró el link
        recientemente, el cron NO debe cancelar la orden — caso runtime
        2026-05-05 #3E10CB92."""
        worker = _make_worker()
        worker._last_release_at = 0.0

        recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        worker.supabase = _stub_supabase_for_release(
            stale_orders=[
                {"id": "order-zombie", "tenant_id": "tenant-1"},
                {"id": "order-stale-no-regen", "tenant_id": "tenant-1"},
            ],
            fresh_payments_by_order={
                # Cliente regeneró link hace 2 min → no cancelar
                "order-zombie": [
                    {"id": "pay-fresh", "created_at": recent_iso},
                ],
                # La otra sin payment fresco → cancelar
            },
        )

        await worker._release_expired_pending_payment_orders()

        self.assertEqual(worker._metrics["expired_orders_cancelled"], 1)
        self.assertEqual(worker.supabase._update_calls, ["order-stale-no-regen"])

    async def test_skips_cancellation_when_payments_lookup_fails(self):
        """Si el lookup de payments explota, el cron es conservador y NO
        cancela (mejor zombie temporal que cancelar orden con cliente
        esperando pago)."""
        worker = _make_worker()
        worker._last_release_at = 0.0

        def _broken_payments_chain():
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.gte.return_value = chain
            chain.limit.return_value = chain
            chain.execute.side_effect = RuntimeError("DB connection lost")
            return chain

        sb = _stub_supabase_for_release(
            stale_orders=[{"id": "order-with-bad-lookup", "tenant_id": "tenant-1"}],
        )

        # Intercepta el route a payments para que falle
        original_table = sb.table.side_effect

        def _table(name):
            if name == "payments":
                return _broken_payments_chain()
            return original_table(name)

        sb.table.side_effect = _table
        worker.supabase = sb

        await worker._release_expired_pending_payment_orders()

        self.assertEqual(worker._metrics["expired_orders_cancelled"], 0)
        self.assertEqual(sb._update_calls, [])

    async def test_no_run_if_disabled(self):
        """Si PENDING_PAYMENT_RELEASE_ENABLED=false, no ejecuta nada."""
        worker = _make_worker()
        worker._release_enabled = False
        worker._last_release_at = 0.0

        await worker._release_expired_pending_payment_orders()

        worker.supabase.table.assert_not_called()

    async def test_respects_interval(self):
        """No ejecuta si el intervalo no ha vencido."""
        worker = _make_worker()
        worker._last_release_at = time.time()

        await worker._release_expired_pending_payment_orders()

        worker.supabase.table.assert_not_called()

    async def test_no_action_when_no_stale_orders(self):
        """Si no hay pedidos expirados, no ejecuta cancellations."""
        worker = _make_worker()
        worker._last_release_at = 0.0
        worker.supabase = _stub_supabase_for_release(stale_orders=[])

        await worker._release_expired_pending_payment_orders()

        self.assertEqual(worker._metrics["expired_orders_cancelled"], 0)
        self.assertEqual(worker.supabase._update_calls, [])

    async def test_ttl_default_is_35_minutes(self):
        """El TTL default debe ser 35 minutos (5 min por encima del link de 30 min)."""
        self.assertEqual(PENDING_PAYMENT_TTL_MINUTES, 35)


if __name__ == "__main__":
    unittest.main()
