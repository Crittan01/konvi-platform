"""Sem 7 F2 cierre 2026-05-21 — Queue fairness round-robin por tenant:

worker ANTES tomaba FIFO global → tenant con 100 msgs bloqueaba a
tenant con 1. AHORA: round-robin intercala tenants.

(La sección de documento parcial slot-filling se retiró con el módulo
muerto `slot_extractors.py` — auditoría 2026-08-13, G16.)
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"),
)

from worker import _round_robin_dequeue_by_tenant  # noqa: E402


# ── Round-robin fairness por tenant ───────────────────────────────────────

class RoundRobinDequeueTests(unittest.TestCase):

    def _msg(self, tid: str, mid: str) -> dict:
        return {"tenant_id": tid, "id": mid, "conversation_id": f"c-{mid}"}

    def test_single_tenant_preserves_fifo(self):
        """Con 1 tenant, comportamiento idéntico a FIFO legacy."""
        pending = [self._msg("A", f"m{i}") for i in range(5)]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        self.assertEqual([m["id"] for m in out], ["m0", "m1", "m2", "m3", "m4"])

    def test_two_tenants_interleave(self):
        """Tenant A con 3 msgs, tenant B con 2 → intercala: A0,B0,A1,B1,A2."""
        pending = [
            self._msg("A", "a0"), self._msg("A", "a1"), self._msg("A", "a2"),
            self._msg("B", "b0"), self._msg("B", "b1"),
        ]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        self.assertEqual(
            [m["id"] for m in out],
            ["a0", "b0", "a1", "b1", "a2"],
        )

    def test_unfair_tenant_does_not_block_others(self):
        """Tenant A con 100 msgs, tenant B con 1 → B NO espera 100 turns.
        Output incluye B en posición 2 (justo después del primer A)."""
        pending = [self._msg("A", f"a{i}") for i in range(100)]
        pending.append(self._msg("B", "b0"))
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        ids = [m["id"] for m in out]
        # Primer msg de B debe estar en los primeros 2 elementos.
        self.assertEqual(ids[1], "b0")
        # El resto son de A (FIFO interno).
        for i in [0, 2, 3, 4, 5, 6, 7, 8, 9]:
            self.assertTrue(ids[i].startswith("a"))

    def test_max_total_respected(self):
        pending = [self._msg("A", f"a{i}") for i in range(50)]
        out = _round_robin_dequeue_by_tenant(pending, max_total=5)
        self.assertEqual(len(out), 5)

    def test_empty_pending_returns_empty(self):
        self.assertEqual(_round_robin_dequeue_by_tenant([], max_total=10), [])

    def test_tenant_order_preserved(self):
        """Si pending viene ordenado por created_at, los primeros tenants
        en aparecer mantienen prioridad inicial en round-robin."""
        pending = [
            self._msg("B", "b0"),  # B aparece primero (más viejo)
            self._msg("A", "a0"),
            self._msg("B", "b1"),
            self._msg("A", "a1"),
        ]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        # B es el primero en first-seen → primer slot.
        self.assertEqual([m["id"] for m in out], ["b0", "a0", "b1", "a1"])


if __name__ == "__main__":
    unittest.main()
