"""BLOQUE J-4 (decisiones founder 2026-07-12) — wiring FSM/tools del bot.

#2 add_to_cart en POST_PAYMENT: el cliente puede iniciar una RE-COMPRA tras pagar
   (carrito nuevo, no modifica la orden pagada). El prompt ya lo invitaba.
#3 fsm_states_denied → escalar a human_takeover: si el tenant apaga un estado, el
   bot NO opera ahí; escala al operador (antes solo logueaba).

(#1 eliminar flags CUSTOMER_CONTEXT muertos y #4 retiro V1 → BLOQUE K.)
"""
import asyncio
import inspect
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.state_machine import AgenticState  # noqa: E402
from agentic.prompt import tools_for_state  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class PostPaymentAddToCartTest(unittest.TestCase):
    def test_post_payment_includes_add_to_cart(self):
        tools = tools_for_state(AgenticState.POST_PAYMENT)
        self.assertIn("add_to_cart", tools)
        # Sigue teniendo lo de post-venta (no reemplacé, agregué).
        self.assertIn("get_recent_orders", tools)
        self.assertIn("escalate_to_human", tools)


class StateDeniedEscalationTest(unittest.TestCase):
    def _mk_recording_supabase(self):
        updates = []
        sb = MagicMock()

        class _Q:
            def __init__(self, tbl):
                self.tbl = tbl
                self.filters = {}
            def __getattr__(self, _n):
                def _chain(*a, **k):
                    if _n == "update":
                        self.payload = a[0] if a else None
                    if _n == "eq" and a:
                        self.filters[a[0]] = a[1]
                    if _n == "insert":
                        pass
                    if _n == "execute":
                        if getattr(self, "payload", None) is not None:
                            updates.append((self.tbl, self.payload, dict(self.filters)))
                        return MagicMock(data=[{"id": "x"}])
                    return self
                return _chain
        sb.table.side_effect = lambda name: _Q(name)
        return sb, updates

    def test_escalate_sets_status_scoped_by_tenant_and_notifies(self):
        # Mecanismo reusado: status→human_takeover, SCOPED por tenant_id (review:
        # un update cross-tenant pasaría en verde si no se verifica el filtro).
        import agentic.dispatcher as d
        sb, updates = self._mk_recording_supabase()
        with patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)) as notify:
            _run(d._escalate_conversation_to_human(
                sb, tenant_id="t-abc", conversation_id="c-1", reason="estado apagado",
            ))
        conv = [(p, f) for t, p, f in updates if t == "conversations"]
        self.assertTrue(conv, "no hubo update a conversations")
        payload, filters = conv[0]
        self.assertEqual(payload.get("status"), "human_takeover")
        self.assertEqual(filters.get("tenant_id"), "t-abc")   # scoped
        self.assertEqual(filters.get("id"), "c-1")
        notify.assert_awaited_once()
        # El reason (no-PII) viaja a la notificación del operador.
        self.assertEqual(notify.call_args.kwargs.get("reason"), "estado apagado")

    def test_denied_state_block_marks_processed_before_return(self):
        # MUTATION-CATCHING del bug HIGH del review: el path denied DEBE marcar el
        # inbound PROCESSED antes del return (si no, queda 'processing' → sweep lo
        # re-despacha → re-envía handoff en loop). Verifica el ORDEN semántico:
        # escalate → _mark_message_processing(PROCESSED) → return → todo ANTES de
        # correr el LLM.
        import agentic.dispatcher as d
        src = inspect.getsource(d._run_agentic_full)
        idx_denied = src.index("if _state_is_denied:")
        idx_escalate = src.index("_escalate_conversation_to_human", idx_denied)
        idx_mark = src.index("_mark_message_processing(", idx_escalate)
        idx_return = src.index("\n        return", idx_mark)
        idx_run_agent = src.index("await run_agentic_turn(")
        self.assertLess(idx_escalate, idx_mark, "escala antes de marcar")
        self.assertLess(idx_mark, idx_return, "marca PROCESSED antes del return")
        self.assertLess(idx_return, idx_run_agent,
                        "el return del denied está ANTES de correr el LLM")
        # El mark usa PROCESSED (no otro estado) en ese bloque.
        denied_block = src[idx_denied:idx_return]
        self.assertIn("PROCESSING_STATUS_PROCESSED", denied_block)

    def test_denied_state_sends_customer_handoff_message(self):
        # El cliente recibe un aviso de handoff (no queda en silencio).
        import agentic.dispatcher as d
        src = inspect.getsource(d._run_agentic_full)
        idx_denied = src.index("if _state_is_denied:")
        idx_return = src.index("\n        return", idx_denied)
        denied_block = src[idx_denied:idx_return]
        self.assertIn("_send_outbound_text", denied_block)
        self.assertIn("especialista", denied_block)


if __name__ == "__main__":
    unittest.main()
