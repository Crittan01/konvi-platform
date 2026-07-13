"""OLA 0 — fault isolation por job en _poll_cycle del worker.

Antes los 13 jobs del ciclo corrían con `await` secuencial SIN try/except → si uno
fallaba (p.ej. wompi void poll), abortaba el resto (SLA, tenant hard-delete, health
metrics dejaban de correr ese ciclo). Fix: cada job va envuelto en `_run_job`, que
aísla la excepción (log + métrica) y deja continuar los siguientes.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from worker import OrchestratorWorker  # noqa: E402

_JOBS = [
    "_sweep_stale_processing_if_due", "_poll_inbound_messages",
    "_poll_human_takeover_notifications", "_poll_whatsapp_outbound_messages",
    "_run_idempotency_cleanup_if_due", "_send_payment_reminders_if_due",
    "_send_cart_abandoned_reminders_if_due", "_release_expired_pending_payment_orders",
    "_poll_wompi_pending_voids_if_due", "_anti_hibernation_ping_if_due",
    "_check_human_takeover_sla_if_due", "_run_tenant_hard_delete_if_due",
    "_collect_health_metrics_if_due",
]


class PollCycleIsolationTests(unittest.TestCase):

    def _stub(self):
        stub = MagicMock(spec=OrchestratorWorker)
        stub._metrics = {"poll_cycles": 0, "poll_job_errors": 0}
        # métodos reales bajo prueba, ligados al stub
        stub._run_job = OrchestratorWorker._run_job.__get__(stub)
        for j in _JOBS:
            setattr(stub, j, AsyncMock())
        return stub

    def test_un_job_que_falla_no_aborta_los_siguientes(self):
        stub = self._stub()
        # el 9º job (wompi void poll) revienta
        stub._poll_wompi_pending_voids_if_due = AsyncMock(side_effect=RuntimeError("boom"))
        asyncio.run(OrchestratorWorker._poll_cycle(stub))
        # los jobs POSTERIORES al que falló SÍ corrieron
        stub._collect_health_metrics_if_due.assert_awaited_once()
        stub._run_tenant_hard_delete_if_due.assert_awaited_once()
        stub._check_human_takeover_sla_if_due.assert_awaited_once()
        # el fallo quedó contabilizado, no propagado
        self.assertEqual(stub._metrics["poll_job_errors"], 1)

    def test_ciclo_limpio_no_incrementa_errores(self):
        stub = self._stub()
        asyncio.run(OrchestratorWorker._poll_cycle(stub))
        self.assertEqual(stub._metrics["poll_job_errors"], 0)
        for j in _JOBS:
            getattr(stub, j).assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
