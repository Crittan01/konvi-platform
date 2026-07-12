"""BLOQUE J-1 (auditoría 2026-07-12) — robustez del worker/connector.

Cubre 4 correcciones de resiliencia:
  1. _mark_outbound_failed envuelto en try/except (un error transitorio del UPDATE
     no debe abortar el resto del batch outbound ni los crons siguientes del tick).
  2. Dead-letter del consumidor de takeover: read_ct >= MAX → ACK + métrica (no
     re-entrega infinita); read_ct < MAX → NO ACK (retry tras VT).
  3. _get_tenant_wa_credentials loguea la excepción (fallo transitorio Vault/DB
     distinguible de "sin credenciales") pero mantiene el retorno ("","").
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import worker  # noqa: E402
from worker import OrchestratorWorker, HUMAN_TAKEOVER_MAX_READ_CT  # noqa: E402


class MarkOutboundFailedTest(unittest.TestCase):
    def test_success_returns_true(self):
        stub = MagicMock(spec=OrchestratorWorker)
        sb = MagicMock()
        sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "m-1"}])
        stub.supabase = sb
        stub._metrics = {}
        ok = OrchestratorWorker._mark_outbound_failed(stub, "t-1", "m-1", "reason")
        self.assertTrue(ok)

    def test_transient_failure_no_propagate_observable(self):
        # El UPDATE lanza en los 3 retries → NO propaga (no aborta el ciclo),
        # retorna False, incrementa métrica alertable y loguea (no silencioso).
        stub = MagicMock(spec=OrchestratorWorker)
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("supabase timeout")
        stub.supabase = sb
        stub._metrics = {}
        with patch("worker.time.sleep"):  # no dormir los backoffs en el test
            with self.assertLogs("orchestrator.worker", level="ERROR") as cm:
                ok = OrchestratorWorker._mark_outbound_failed(stub, "t-1", "m-1", "reason")
        self.assertFalse(ok)
        self.assertEqual(stub._metrics.get("wa_outbound_mark_failed_stuck"), 1)
        self.assertTrue(any("mark_failed_stuck" in m for m in cm.output))

    def test_retries_three_times_before_giving_up(self):
        stub = MagicMock(spec=OrchestratorWorker)
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("timeout")
        stub.supabase = sb
        stub._metrics = {}
        with patch("worker.time.sleep") as sleep_mock:
            OrchestratorWorker._mark_outbound_failed(stub, "t-1", "m-1", "r")
        # 3 intentos → 2 sleeps entre ellos.
        self.assertEqual(sleep_mock.call_count, 2)

    def test_noop_without_ids(self):
        stub = MagicMock(spec=OrchestratorWorker)
        stub.supabase = MagicMock()
        ok = OrchestratorWorker._mark_outbound_failed(stub, "", "m-1", "r")
        self.assertFalse(ok)
        stub.supabase.table.assert_not_called()


class TakeoverDeadLetterTest(unittest.TestCase):
    def _run_consumer(self, *, read_ct, handled):
        import asyncio

        acked = []
        event = {"msg_id": 42, "read_ct": read_ct, "message": {"conversation_id": "c-1"}}
        sb = MagicMock()
        rpc_res = MagicMock(data=[event])
        sb.rpc.return_value.execute.return_value = rpc_res

        stub = MagicMock(spec=OrchestratorWorker)
        stub.supabase = sb
        stub._queue_runtime_enabled = True
        stub._metrics = {"takeover_events_seen": 0}
        stub._ack_human_takeover_message = lambda mid: acked.append(mid)

        # Patch vía el __globals__ del método (no `patch("worker.X")`): si otro
        # test del suite recargó el módulo dispatcher/worker (test_dispatcher.py
        # hace importlib.reload), sys.modules['worker'] puede diferir del dict de
        # globals desde el que el método resuelve el símbolo. Parchear el dict
        # exacto que usa el método es inmune a esa contaminación cross-test.
        g = OrchestratorWorker._poll_human_takeover_notifications.__globals__
        orig = g.get("dispatch_human_takeover_event")
        g["dispatch_human_takeover_event"] = AsyncMock(return_value=handled)
        try:
            asyncio.new_event_loop().run_until_complete(
                OrchestratorWorker._poll_human_takeover_notifications(stub)
            )
        finally:
            g["dispatch_human_takeover_event"] = orig
        return acked, stub._metrics

    def test_unhandled_over_threshold_dead_letters(self):
        acked, metrics = self._run_consumer(read_ct=HUMAN_TAKEOVER_MAX_READ_CT, handled=False)
        self.assertEqual(acked, [42])  # ACK (dead-letter)
        self.assertEqual(metrics.get("takeover_events_dead_lettered"), 1)

    def test_unhandled_under_threshold_no_ack(self):
        acked, metrics = self._run_consumer(read_ct=1, handled=False)
        self.assertEqual(acked, [])  # NO ACK → retry tras VT
        self.assertNotIn("takeover_events_dead_lettered", metrics)

    def test_handled_acks_and_skips_dead_letter_accounting(self):
        # handled=True ACK sin importar read_ct, y NO cuenta dead-letter.
        acked, metrics = self._run_consumer(read_ct=99, handled=True)
        self.assertEqual(acked, [42])
        self.assertNotIn("takeover_events_dead_lettered", metrics)

    def test_missing_read_ct_field_coerces_to_zero(self):
        # Evento viejo sin read_ct → int(None or 0)=0 < umbral → NO dead-letter.
        import asyncio
        acked = []
        event = {"msg_id": 7, "message": {"conversation_id": "c-1"}}  # sin read_ct
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[event])
        stub = MagicMock(spec=OrchestratorWorker)
        stub.supabase = sb
        stub._queue_runtime_enabled = True
        stub._metrics = {"takeover_events_seen": 0}
        stub._ack_human_takeover_message = lambda mid: acked.append(mid)
        g = OrchestratorWorker._poll_human_takeover_notifications.__globals__
        orig = g.get("dispatch_human_takeover_event")
        g["dispatch_human_takeover_event"] = AsyncMock(return_value=False)
        try:
            asyncio.new_event_loop().run_until_complete(
                OrchestratorWorker._poll_human_takeover_notifications(stub)
            )
        finally:
            g["dispatch_human_takeover_event"] = orig
        self.assertEqual(acked, [])  # no ACK, no dead-letter


class GetTenantWaCredentialsTest(unittest.TestCase):
    def test_logs_exception_returns_empty(self):
        from whatsapp_sender import _get_tenant_wa_credentials
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("vault down")
        with self.assertLogs("orchestrator.whatsapp_sender", level="ERROR") as cm:
            phone, token = _get_tenant_wa_credentials("t-abc12345", sb)
        self.assertEqual((phone, token), ("", ""))
        self.assertTrue(any("_get_tenant_wa_credentials error" in m for m in cm.output))

    def test_not_connected_returns_empty_no_log(self):
        from whatsapp_sender import _get_tenant_wa_credentials
        sb = MagicMock()
        q = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value
        q.execute.return_value = types.SimpleNamespace(data={"status": "disconnected"})
        with self.assertNoLogs("orchestrator.whatsapp_sender", level="ERROR"):
            phone, token = _get_tenant_wa_credentials("t-1", sb)
        self.assertEqual((phone, token), ("", ""))

    def test_no_integration_row_returns_empty_no_error_log(self):
        # BLOQUE J (review): tenant sin fila WhatsApp (maybe_single → data=None) es
        # benigno → NO debe loguear "¿Vault/DB transitorio?".
        from whatsapp_sender import _get_tenant_wa_credentials
        sb = MagicMock()
        q = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value
        q.execute.return_value = types.SimpleNamespace(data=None)
        with self.assertNoLogs("orchestrator.whatsapp_sender", level="ERROR"):
            phone, token = _get_tenant_wa_credentials("t-1", sb)
        self.assertEqual((phone, token), ("", ""))


class HeartbeatInLoopsTest(unittest.TestCase):
    """Verifica (vía AST, no grep) que el heartbeat está DENTRO del for-loop —
    la preocupación concreta del review: 'cannot verify it is INSIDE the loop'."""

    def _heartbeat_is_inside_a_for_loop(self, method) -> bool:
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))

        def _assigns_heartbeat(node) -> bool:
            return (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Attribute) and t.attr == "last_heartbeat_ts"
                    for t in node.targets
                )
            )

        for for_node in ast.walk(tree):
            if not isinstance(for_node, ast.For):
                continue
            # Buscar la asignación como statement DIRECTO del cuerpo del for.
            for stmt in for_node.body:
                if _assigns_heartbeat(stmt):
                    return True
        return False

    def test_reminder_loop_beats_inside_for(self):
        self.assertTrue(
            self._heartbeat_is_inside_a_for_loop(
                OrchestratorWorker._send_payment_reminders_if_due
            )
        )

    def test_cart_abandoned_loop_beats_inside_for(self):
        self.assertTrue(
            self._heartbeat_is_inside_a_for_loop(
                OrchestratorWorker._send_cart_abandoned_reminders_if_due
            )
        )


if __name__ == "__main__":
    unittest.main()
