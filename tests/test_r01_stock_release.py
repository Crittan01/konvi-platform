"""
Tests R-01: Liberación de pedidos pending_payment expirados.
Verifica que el worker cancela pedidos sin pago después del TTL,
sin afectar pedidos recientes ni los ya confirmados.
"""
import os
import sys
import asyncio
import time
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from worker import OrchestratorWorker, PENDING_PAYMENT_TTL_MINUTES


def _make_worker():
    with patch("worker.create_client") as mock_client:
        mock_client.return_value = MagicMock()
        w = OrchestratorWorker()
    return w


class PendingPaymentReleaseTests(unittest.IsolatedAsyncioTestCase):

    async def test_cancels_stale_pending_payment_orders(self):
        """Pedidos en pending_payment más viejos del TTL deben cancelarse."""
        worker = _make_worker()
        worker._last_release_at = 0.0  # forzar ejecución inmediata

        stale_orders = [
            {"id": "order-1", "tenant_id": "tenant-1"},
            {"id": "order-2", "tenant_id": "tenant-1"},
        ]

        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=stale_orders)

        mock_update = MagicMock()
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": "order-1"}])

        worker.supabase.table.return_value.select.return_value.eq.return_value.lt.return_value.limit.return_value = mock_select
        worker.supabase.table.return_value.update.return_value.eq.return_value.eq.return_value = mock_update

        await worker._release_expired_pending_payment_orders()

        # Verifica que se intentó cancelar los 2 pedidos
        self.assertEqual(worker._metrics["expired_orders_cancelled"], 2)

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
        worker._last_release_at = time.time()  # just ran

        await worker._release_expired_pending_payment_orders()

        worker.supabase.table.assert_not_called()

    async def test_no_action_when_no_stale_orders(self):
        """Si no hay pedidos expirados, no ejecuta cancellations."""
        worker = _make_worker()
        worker._last_release_at = 0.0

        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[])
        worker.supabase.table.return_value.select.return_value.eq.return_value.lt.return_value.limit.return_value = mock_select

        await worker._release_expired_pending_payment_orders()

        # update no debe llamarse
        worker.supabase.table.return_value.update.assert_not_called()
        self.assertEqual(worker._metrics["expired_orders_cancelled"], 0)

    async def test_ttl_default_is_35_minutes(self):
        """El TTL default debe ser 35 minutos (5 min por encima del link de 30 min)."""
        self.assertEqual(PENDING_PAYMENT_TTL_MINUTES, 35)


if __name__ == "__main__":
    unittest.main()
