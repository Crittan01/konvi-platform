"""G9 — split del worker en dos loops asyncio + métrica inbound_lag_seconds.

Cubre:
  • Compat de `_poll_cycle` (contrato legado de test_ola0): los 21 jobs corren
    aislados y en el ORDEN histórico (inbound primero).
  • `_loop`: contador por grupo, heartbeat por loop, salida con stop().
  • `run()`: lanza los dos loops (inbound + maintenance) vía gather.
  • `_record_inbound_lag`: cola vacía → 0, lag = edad del más viejo, fecha
    malformada no rompe el poll.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

# OJO: worker.py lee NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SECRET_KEY a
# nivel MÓDULO (import time) — setear esas (no otras) ANTES del import, o los
# tests que instancian OrchestratorWorker real quedan sin config (orden de
# colección: este archivo se importa antes que varios de ellos).
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import worker as worker_mod  # noqa: E402
from worker import OrchestratorWorker  # noqa: E402

_ALL_METHODS = [attr for _, attr in (*worker_mod._INBOUND_JOBS, *worker_mod._MAINTENANCE_JOBS)]


def _stub() -> MagicMock:
    stub = MagicMock(spec=OrchestratorWorker)
    stub._metrics = {"poll_cycles": 0, "poll_job_errors": 0}
    stub._run_job = OrchestratorWorker._run_job.__get__(stub)
    for m in _ALL_METHODS:
        setattr(stub, m, AsyncMock())
    return stub


class PollCycleCompatTests(unittest.TestCase):
    def test_grupos_suman_los_21_jobs_sin_solape(self):
        self.assertEqual(len(worker_mod._INBOUND_JOBS), 4)
        self.assertEqual(len(worker_mod._MAINTENANCE_JOBS), 17)
        attrs_inbound = {a for _, a in worker_mod._INBOUND_JOBS}
        attrs_maint = {a for _, a in worker_mod._MAINTENANCE_JOBS}
        self.assertFalse(attrs_inbound & attrs_maint)

    def test_poll_cycle_corre_todos_aislados(self):
        stub = _stub()
        asyncio.run(OrchestratorWorker._poll_cycle(stub))
        for m in _ALL_METHODS:
            getattr(stub, m).assert_awaited_once()
        self.assertEqual(stub._metrics["poll_cycles"], 1)
        self.assertEqual(stub._metrics["poll_job_errors"], 0)

    def test_orden_historico_preservado(self):
        stub = _stub()
        calls: list[str] = []
        for m in _ALL_METHODS:
            setattr(stub, m, AsyncMock(side_effect=lambda *a, _m=m, **k: calls.append(_m)))
        asyncio.run(OrchestratorWorker._poll_cycle(stub))
        self.assertEqual(calls, _ALL_METHODS)


class LoopTests(unittest.TestCase):
    def _loop_stub(self) -> MagicMock:
        stub = MagicMock(spec=OrchestratorWorker)
        stub._metrics = {}
        stub._running = True
        stub.last_heartbeat_ts = 0.0
        stub.last_maintenance_heartbeat_ts = 0.0
        stub._run_job = OrchestratorWorker._run_job.__get__(stub)
        return stub

    def test_loop_inbound_cuenta_ciclos_y_marca_heartbeat_principal(self):
        stub = self._loop_stub()
        job = AsyncMock(side_effect=lambda: setattr(stub, "_running", False))
        stub._demo_job = job
        asyncio.run(asyncio.wait_for(
            OrchestratorWorker._loop(stub, "inbound", (("demo", "_demo_job"),), 0),
            timeout=5,
        ))
        self.assertEqual(stub._metrics.get("inbound_cycles"), 1)
        job.assert_awaited_once()
        self.assertGreater(stub.last_heartbeat_ts, 0)
        self.assertEqual(stub.last_maintenance_heartbeat_ts, 0.0)

    def test_loop_maintenance_marca_su_propio_heartbeat(self):
        stub = self._loop_stub()
        job = AsyncMock(side_effect=lambda: setattr(stub, "_running", False))
        stub._demo_job = job
        asyncio.run(asyncio.wait_for(
            OrchestratorWorker._loop(stub, "maintenance", (("demo", "_demo_job"),), 0),
            timeout=5,
        ))
        self.assertEqual(stub._metrics.get("maintenance_cycles"), 1)
        self.assertGreater(stub.last_maintenance_heartbeat_ts, 0)
        self.assertEqual(stub.last_heartbeat_ts, 0.0)  # el principal NO lo toca


class RunSplitTests(unittest.TestCase):
    def test_run_lanza_los_dos_loops_con_sus_grupos(self):
        stub = MagicMock(spec=OrchestratorWorker)
        stub._sweep_stale_messages_on_startup = AsyncMock()
        loop_calls: list[tuple[str, int]] = []

        async def fake_loop(label, jobs, interval):
            loop_calls.append((label, len(jobs)))

        stub._loop = fake_loop
        asyncio.run(asyncio.wait_for(OrchestratorWorker.run(stub), timeout=5))
        self.assertEqual(loop_calls, [("inbound", 4), ("maintenance", 17)])
        stub._sweep_stale_messages_on_startup.assert_awaited_once()


class InboundLagTests(unittest.TestCase):
    def _stub_metrics(self) -> MagicMock:
        stub = MagicMock(spec=OrchestratorWorker)
        stub._metrics = {"inbound_lag_seconds": -1.0}
        stub._record_inbound_lag = OrchestratorWorker._record_inbound_lag.__get__(stub)
        return stub

    def test_cola_vacia_pone_cero(self):
        stub = self._stub_metrics()
        stub._record_inbound_lag([])
        self.assertEqual(stub._metrics["inbound_lag_seconds"], 0.0)

    def test_lag_es_la_edad_del_mas_viejo(self):
        stub = self._stub_metrics()
        viejo = (datetime.now(timezone.utc) - timedelta(seconds=42)).isoformat()
        nuevo = datetime.now(timezone.utc).isoformat()
        stub._record_inbound_lag([{"created_at": nuevo}, {"created_at": viejo}])
        lag = stub._metrics["inbound_lag_seconds"]
        self.assertGreaterEqual(lag, 41.0)
        self.assertLess(lag, 60.0)

    def test_created_at_malformado_no_rompe(self):
        stub = self._stub_metrics()
        stub._record_inbound_lag([{"created_at": "no-es-fecha"}])  # no lanza
        stub._record_inbound_lag([{}])  # sin created_at: tampoco lanza


if __name__ == "__main__":
    unittest.main()
