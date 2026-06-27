"""Worker-robustez (2026-06-27) — recuperación de mensajes huérfanos + coalescing.

Capa A: _reclaim_stale_inbound re-encola 'processing' atascados (failed si max attempts) +
gate periódico _sweep_stale_processing_if_due. Coalescing: _coalesce_pending_by_conversation
captura fragmentos tardíos vía re-fetch y los combina (coalesce-first preservado).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from worker import OrchestratorWorker, MAX_PROCESSING_ATTEMPTS  # noqa: E402


class _RecTable:
    """Tabla mock que registra updates y devuelve filas configurables por op."""
    def __init__(self, store):
        self.store = store
        self._op = None
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        m = MagicMock()
        if self._op == "select":
            m.data = self.store.get("select_rows", [])
        else:
            self.store.setdefault("updates", []).append(self._payload)
            m.data = self.store.get("update_returns", [{"id": "x"}])
        return m


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _RecTable(self.store)


def _worker(store):
    w = OrchestratorWorker.__new__(OrchestratorWorker)
    w.supabase = _FakeSB(store)
    w._metrics = {}
    w._last_stale_sweep_at = 0.0
    return w


class ReclaimStaleTests(unittest.TestCase):
    def test_reclaims_processing_under_max_to_pending(self):
        store = {"select_rows": [
            {"id": "m1", "processing_attempts": 1, "tenant_id": "t1"},
        ]}
        w = _worker(store)
        asyncio.run(w._reclaim_stale_inbound(
            threshold_minutes=3, statuses=["processing"], label="PERIODIC"))
        statuses = [u.get("processing_status") for u in store.get("updates", [])]
        self.assertIn("pending", statuses)
        self.assertNotIn("failed", statuses)

    def test_abandons_processing_at_max_attempts_to_failed(self):
        store = {"select_rows": [
            {"id": "m2", "processing_attempts": MAX_PROCESSING_ATTEMPTS, "tenant_id": "t1"},
        ]}
        w = _worker(store)
        asyncio.run(w._reclaim_stale_inbound(
            threshold_minutes=3, statuses=["processing"], label="PERIODIC"))
        statuses = [u.get("processing_status") for u in store.get("updates", [])]
        self.assertIn("failed", statuses)
        self.assertNotIn("pending", statuses)

    def test_no_stale_no_updates(self):
        store = {"select_rows": []}
        w = _worker(store)
        asyncio.run(w._reclaim_stale_inbound(
            threshold_minutes=3, statuses=["processing"], label="PERIODIC"))
        self.assertEqual(store.get("updates", []), [])


class StaleSweepGateTests(unittest.TestCase):
    def test_gate_skips_when_recent(self):
        store = {"select_rows": [{"id": "m", "processing_attempts": 1, "tenant_id": "t1"}]}
        w = _worker(store)
        import time
        w._last_stale_sweep_at = time.time()  # recién corrido
        asyncio.run(w._sweep_stale_processing_if_due())
        # No debió tocar nada (gate bloquea).
        self.assertEqual(store.get("updates", []), [])

    def test_gate_runs_when_due(self):
        store = {"select_rows": [{"id": "m", "processing_attempts": 1, "tenant_id": "t1"}]}
        w = _worker(store)
        w._last_stale_sweep_at = 0.0  # nunca corrido → due
        asyncio.run(w._sweep_stale_processing_if_due())
        self.assertIn("pending", [u.get("processing_status") for u in store.get("updates", [])])


class CoalesceFirstFragmentTests(unittest.TestCase):
    def test_refetch_captures_late_fragment_and_combines(self):
        # Coalesce-first: el lead es reciente → espera; el re-fetch (todos los pending)
        # captura el fragmento tardío de la misma conv → se combinan en uno.
        from datetime import datetime, timedelta, timezone
        t0 = datetime.now(timezone.utc)
        lead = {"id": "m1", "tenant_id": "t1", "conversation_id": "c1",
                "content": "Quiero un jabón", "content_type": "text",
                "processing_attempts": 0, "created_at": t0.isoformat()}
        fragment = {"id": "m2", "tenant_id": "t1", "conversation_id": "c1",
                    "content": "de Coco", "content_type": "text",
                    "processing_attempts": 0,
                    "created_at": (t0 + timedelta(seconds=1)).isoformat()}
        # El re-fetch devuelve TODOS los pending (lead + fragmento), como en la DB real.
        store = {"select_rows": [lead, fragment]}
        w = _worker(store)
        with patch("worker.asyncio.sleep", new=_async_noop):
            result = asyncio.run(w._coalesce_pending_by_conversation([lead]))
        self.assertEqual(len(result), 1)
        combined = result[0]["content"]
        self.assertIn("Quiero un jabón", combined)
        self.assertIn("de Coco", combined)


async def _async_noop(*a, **k):
    return None


if __name__ == "__main__":
    unittest.main()
