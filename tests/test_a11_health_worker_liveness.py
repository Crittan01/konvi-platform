"""Regresión A11 audit (2026-06-25) — /health refleja la salud REAL del worker.

Antes: /health devolvía 200 incondicional. Si el thread del worker moría o se
colgaba, Render seguía viendo 200 → no auto-reiniciaba → outage silencioso
(mensajes inbound sin procesar). Fix: heartbeat + /health → 503 si worker
caído/colgado.

Se invoca `health()` directamente (no TestClient) para NO disparar el startup
event que lanzaría un worker real contra Supabase.
"""
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import server  # noqa: E402


class _FakeWorker:
    def __init__(self, hb_ts):
        self.last_heartbeat_ts = hb_ts


class HealthWorkerLivenessTests(unittest.TestCase):
    def setUp(self):
        self._orig_status = server._worker_status
        self._orig_ref = server._worker_ref
        self.addCleanup(self._restore)

    def _restore(self):
        server._worker_status = self._orig_status
        server._worker_ref = self._orig_ref

    def test_ok_when_worker_running_and_fresh(self):
        server._worker_status = {"running": True, "started_at": "x", "error": None}
        server._worker_ref = {"instance": _FakeWorker(time.time())}
        r = server.health()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["status"], "ok")

    def test_503_when_worker_not_running(self):
        server._worker_status = {"running": False, "error": None}
        server._worker_ref = {"instance": _FakeWorker(time.time())}
        r = server.health()
        self.assertEqual(getattr(r, "status_code", 200), 503)

    def test_503_when_worker_error(self):
        server._worker_status = {"running": True, "error": "boom"}
        server._worker_ref = {"instance": _FakeWorker(time.time())}
        r = server.health()
        self.assertEqual(getattr(r, "status_code", 200), 503)

    def test_503_when_heartbeat_stale(self):
        stale = time.time() - (server.HEALTH_HEARTBEAT_STALE_SECONDS + 60)
        server._worker_status = {"running": True, "error": None}
        server._worker_ref = {"instance": _FakeWorker(stale)}
        r = server.health()
        self.assertEqual(getattr(r, "status_code", 200), 503)

    def test_ok_during_startup_window_no_instance_yet(self):
        # Worker thread arrancó (running=True) pero la instancia aún no existe →
        # no debe dar 503 (evita falso-negativo de Render al boot).
        server._worker_status = {"running": True, "error": None}
        server._worker_ref = {"instance": None}
        r = server.health()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["status"], "ok")


if __name__ == "__main__":
    unittest.main()
