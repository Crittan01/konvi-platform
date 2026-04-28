"""Tests del ACK transaccional en worker._mark_outbound_sent.

B2: tras Meta entregar el mensaje, el UPDATE en DB para registrar
meta_message_id puede fallar. La función debe reintentar 3 veces y, si
todos fallan, marcar el mensaje como ack_pending para reconciliación
manual. NO debe lanzar excepción al caller (la cola pgmq ya hace ACK
para evitar duplicar el envío en Meta).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")


def _make_worker(supabase):
    """Construye un OrchestratorWorker con un supabase mock."""
    from worker import OrchestratorWorker
    w = OrchestratorWorker.__new__(OrchestratorWorker)
    w.supabase = supabase
    w._metrics = {}
    return w


class _UpdateExecutor:
    """Cuenta cuántas veces se llamó execute() y permite que falle un número específico."""
    def __init__(self, fail_first_n: int = 0):
        self.fail_first_n = fail_first_n
        self.call_count = 0
        self.payloads: list = []

    def update(self, payload):
        self.payloads.append(payload)
        return self

    def eq(self, *_a, **_kw):
        return self

    def execute(self):
        self.call_count += 1
        if self.call_count <= self.fail_first_n:
            raise RuntimeError(f"DB error #{self.call_count}")
        m = MagicMock()
        m.data = []
        return m


def _supabase_with_executor(executor):
    sb = MagicMock()
    sb.table.return_value = executor
    return sb


class AckTransactionalTests(unittest.TestCase):

    def test_happy_path_returns_true_on_first_try(self):
        executor = _UpdateExecutor(fail_first_n=0)
        sb = _supabase_with_executor(executor)
        worker = _make_worker(sb)
        ok = worker._mark_outbound_sent("tenant-1", "msg-1", "wamid.X")
        self.assertTrue(ok)
        self.assertEqual(executor.call_count, 1)
        # Payload incluye meta_message_id y status processed
        self.assertEqual(executor.payloads[0]["meta_message_id"], "wamid.X")
        self.assertEqual(executor.payloads[0]["processing_status"], "processed")

    def test_retries_after_db_failure_then_succeeds(self):
        executor = _UpdateExecutor(fail_first_n=2)
        sb = _supabase_with_executor(executor)
        worker = _make_worker(sb)
        # Patch time.sleep para no esperar realmente.
        with patch("worker.time.sleep"):
            ok = worker._mark_outbound_sent("tenant-1", "msg-2", "wamid.Y")
        self.assertTrue(ok)
        self.assertEqual(executor.call_count, 3)

    def test_three_failures_marks_ack_pending_returns_false(self):
        # Falla los 3 intentos del processed; el fallback ack_pending tiene
        # éxito (mismo executor pero con call_count >= 3 deja de fallar — pero
        # nuestro contador se mantiene, así que el fallback será el call_count=4).
        executor = _UpdateExecutor(fail_first_n=3)
        sb = _supabase_with_executor(executor)
        worker = _make_worker(sb)
        with patch("worker.time.sleep"):
            ok = worker._mark_outbound_sent("tenant-1", "msg-3", "wamid.Z")
        self.assertFalse(ok)
        # 3 intentos processed + 1 fallback ack_pending = 4 calls
        self.assertEqual(executor.call_count, 4)
        # El último payload debe ser ack_pending
        self.assertEqual(executor.payloads[-1]["processing_status"], "ack_pending")
        self.assertIn("ack_pending", executor.payloads[-1].get("last_error", "").lower())

    def test_three_failures_and_ack_pending_failure_does_not_raise(self):
        # Hasta el fallback ack_pending falla. El método NO debe propagar excepción
        # — solo loggea critical y retorna False.
        executor = _UpdateExecutor(fail_first_n=10)  # todos los calls fallan
        sb = _supabase_with_executor(executor)
        worker = _make_worker(sb)
        with patch("worker.time.sleep"):
            ok = worker._mark_outbound_sent("tenant-1", "msg-4", "wamid.W")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
