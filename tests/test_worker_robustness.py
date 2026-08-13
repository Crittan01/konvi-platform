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
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from worker import OrchestratorWorker, MAX_PROCESSING_ATTEMPTS  # noqa: E402


class _RecTable:
    """Tabla mock que registra updates y devuelve filas configurables por op/filtros."""
    def __init__(self, store):
        self.store = store
        self._op = None
        self._payload = None
        self._filters = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, k=None, v=None):
        if k is not None:
            self._filters[k] = v
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
            conv_rows = self.store.get("conv_rows")
            seq = self.store.get("select_sequence")
            if conv_rows is not None:
                m.data = conv_rows.get(self._filters.get("conversation_id"), [])
            elif seq is not None:
                idx = self.store.get("_seq_idx", 0)
                m.data = seq[min(idx, len(seq) - 1)]
                self.store["_seq_idx"] = idx + 1
            else:
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


async def _async_noop(*a, **k):
    return None


class _SleepSpy:
    def __init__(self):
        self.count = 0
        self.total = 0.0

    async def __call__(self, secs):
        self.count += 1
        self.total += secs


def _msg(id_, conv_id, content, age_seconds):
    from datetime import datetime, timedelta, timezone
    return {
        "id": id_, "tenant_id": "t1", "conversation_id": conv_id,
        "content": content, "content_type": "text", "processing_attempts": 0,
        "created_at": (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat(),
    }


class BatchAgesTests(unittest.TestCase):
    def test_oldest_and_newest(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        pending = [_msg("m1", "c1", "a", 10), _msg("m2", "c1", "b", 2)]
        oldest, newest = OrchestratorWorker._batch_ages(pending, now)
        self.assertGreater(oldest, 9)      # más viejo ~10s
        self.assertLess(newest, 4)         # más nuevo ~2s

    def test_inf_when_no_timestamps(self):
        from datetime import datetime, timezone
        oldest, newest = OrchestratorWorker._batch_ages(
            [{"id": "x", "conversation_id": "c1"}], datetime.now(timezone.utc))
        self.assertEqual(newest, float("inf"))  # sin ts → procesar ya


class DebounceNonBlockingTests(unittest.TestCase):
    """Debounce NO-BLOQUEANTE por conversación (re-fetch scopeado por conv_rows)."""

    def test_silence_reached_combines_and_no_sleep(self):
        # conv c1 con 2 mensajes ya viejos (silencio) → listo → combinado en 1, SIN sleep.
        store = {"conv_rows": {"c1": [
            _msg("m1", "c1", "Quiero un jabón", 8),
            _msg("m2", "c1", "de Coco", 6)]}}
        w = _worker(store)
        spy = _SleepSpy()
        with patch("worker.asyncio.sleep", new=spy):
            result = asyncio.run(w._coalesce_pending_by_conversation(
                [_msg("m1", "c1", "Quiero un jabón", 8)]))
        self.assertEqual(spy.count, 0)  # NO bloquea el ciclo
        self.assertEqual(len(result), 1)
        self.assertIn("Quiero un jabón", result[0]["content"])
        self.assertIn("de Coco", result[0]["content"])

    def test_still_typing_returns_empty(self):
        # Mensaje fresco (sigue escribiendo) → NO listo → [] (se reevalúa próximo poll).
        store = {"conv_rows": {"c1": [_msg("m1", "c1", "Hola", 1)]}}
        w = _worker(store)
        spy = _SleepSpy()
        with patch("worker.asyncio.sleep", new=spy):
            result = asyncio.run(w._coalesce_pending_by_conversation(
                [_msg("m1", "c1", "Hola", 1)]))
        self.assertEqual(spy.count, 0)
        self.assertEqual(result, [])

    def test_cap_processes_even_if_typing(self):
        # Más viejo > tope (25s) → listo aunque el último sea fresco (no colgar).
        store = {"conv_rows": {"c1": [
            _msg("mold", "c1", "primero", 26),
            _msg("mnew", "c1", "ultimo", 1)]}}
        w = _worker(store)
        result = asyncio.run(w._coalesce_pending_by_conversation(
            [_msg("mold", "c1", "primero", 26)]))
        self.assertEqual(len(result), 1)
        self.assertIn("primero", result[0]["content"])
        self.assertIn("ultimo", result[0]["content"])

    def test_per_conversation_isolation(self):
        # [A1] fix: conv A en silencio (lista) + conv B escribiendo (no lista) → SOLO A.
        # Que A esté lista NO debe forzar el proceso de B (antes el tope global lo cortaba).
        store = {"conv_rows": {
            "cA": [_msg("a1", "cA", "listo A", 8)],         # silencio → lista
            "cB": [_msg("b1", "cB", "escribiendo B", 1)],   # fresca → NO lista
        }}
        w = _worker(store)
        result = asyncio.run(w._coalesce_pending_by_conversation(
            [_msg("a1", "cA", "listo A", 8), _msg("b1", "cB", "escribiendo B", 1)]))
        self.assertEqual({r["conversation_id"] for r in result}, {"cA"})


class CoalesceClaimNonTerminalTests(unittest.TestCase):
    """F48 — _combine_by_conversation reclama los fragmentos viejos a 'processing'
    (NO 'processed' terminal) y adjunta _coalesced_ids al dict combinado, para que un
    dispatch fallido pueda recuperar el TURNO COMPLETO (el sweep periódico solo
    reclama 'processing'; un 'processed' antes del dispatch era irrecuperable)."""

    def test_older_fragments_claimed_non_terminal(self):
        from worker import PROCESSING_STATUS_PROCESSING
        store = {}
        w = _worker(store)
        combined = w._combine_by_conversation([
            _msg("m1", "c1", "Hola", 10),
            _msg("m2", "c1", "quiero jabón", 9),
            _msg("m3", "c1", "de coco", 8),
        ])
        # 1 dict combinado (el último con el content unido).
        self.assertEqual(len(combined), 1)
        last = combined[0]
        self.assertEqual(last["id"], "m3")
        # Adjunta ids de los fragmentos viejos + tenant para finalizar/resetear luego.
        self.assertEqual(last["_coalesced_ids"], ["m1", "m2"])
        self.assertEqual(last["_coalesced_tenant_id"], "t1")
        # El claim de los viejos es NO-terminal 'processing' — nunca 'processed'.
        updates = store.get("updates", [])
        self.assertTrue(updates, "no se registró el claim de los fragmentos viejos")
        claim = updates[0]
        self.assertEqual(claim["processing_status"], PROCESSING_STATUS_PROCESSING)
        self.assertNotIn("processed", claim)      # no marca terminal antes del dispatch
        self.assertNotIn("skip_reason", claim)    # skip_reason se pone SOLO al finalizar

    def test_single_message_no_claim(self):
        store = {}
        w = _worker(store)
        combined = w._combine_by_conversation([_msg("m1", "c1", "Hola", 10)])
        self.assertEqual(len(combined), 1)
        self.assertNotIn("_coalesced_ids", combined[0])
        self.assertEqual(store.get("updates", []), [])  # sin coalesce → sin claim


if __name__ == "__main__":
    unittest.main()
