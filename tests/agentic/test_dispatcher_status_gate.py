"""Test: dispatcher gate de conversation status.

Rev. 107 — bug runtime KAIU 2026-05-23: bot respondió a mensaje en
conv con status `human_takeover`, sobrescribiendo al operador. El
gate existía en legacy (orchestrator.py:6754) pero el agentic
dispatcher saltaba directo a `_run_agentic_full` sin verificar.

Fix: gate prerequisito en `dispatch_message()` que skipea bot
si conv.status ∈ {human_takeover, closed}.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_sb(conv_status: str):
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"status": conv_status}] if conv_status else [],
    )
    # B-1 (F7): con status=bot_active el gate consulta la ventana de cortesía
    # del operador (…gt("created_at", …).execute() con head=count) → aquí sin
    # operador reciente (count=0).
    chain.gt.return_value = MagicMock(
        execute=MagicMock(return_value=MagicMock(count=0, data=[])),
    )
    sb.table.return_value = chain
    return sb


class DispatcherStatusGateTests(unittest.TestCase):

    def test_skip_si_conv_human_takeover(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("human_takeover")
        self.assertTrue(_should_skip_for_conv_status(sb, "t1", "conv-1"))

    def test_skip_si_conv_closed(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("closed")
        self.assertTrue(_should_skip_for_conv_status(sb, "t1", "conv-1"))

    def test_no_skip_si_conv_bot_active(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("bot_active")
        self.assertFalse(_should_skip_for_conv_status(sb, "t1", "conv-1"))

    def test_no_skip_si_conv_no_existe(self):
        """Si conv no existe (caso raro), no skipea — deja al legacy fallar."""
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("")  # data vacía
        self.assertFalse(_should_skip_for_conv_status(sb, "t1", "conv-1"))

    def test_no_skip_si_db_falla(self):
        """Error leyendo conv → no skipea (default permisivo)."""
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("db down")
        self.assertFalse(_should_skip_for_conv_status(sb, "t1", "conv-1"))

    def test_dispatch_message_human_takeover_NO_llama_agentic_NI_legacy(self):
        """End-to-end: dispatch_message en conv human_takeover NO debe invocar
        ni _run_agentic_full ni build_and_run_orchestration."""
        import agentic.dispatcher as dispatcher_mod

        sb = _make_sb("human_takeover")
        # Marcar el message como skipped retorna OK.
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch.object(dispatcher_mod, "_run_agentic_full", new=AsyncMock()) as mock_agentic:
            with patch.object(dispatcher_mod, "is_tenant_agentic_enabled",
                              new=AsyncMock(return_value=True)):
                _run(dispatcher_mod.dispatch_message(
                    sb, message_id="msg-1", tenant_id="t",
                    conversation_id="c", content="test",
                    content_type="text",
                ))
        mock_agentic.assert_not_called()


class DispatchTurnContextWiringTests(unittest.TestCase):
    """B-2 Fase 1: el TurnContext nace en dispatch_message y la lectura de la
    conversación se COMPARTE entre el skip gate y el path agentic (antes: el
    skip gate leía `conversations` y el ctx re-leía — INV-B §2 conv×7/turno).
    Además: el gate de opt-out usa el RETURN del handler (P11 — muere la
    re-lectura post-hoc de status)."""

    def _sb(self, status: str):
        from helpers.supabase_mocks import FakeSupabase
        sb = FakeSupabase()
        sb.data["conversations"] = [{
            "status": status, "agentic_state": None,
            "customer_phone": "573001112233",
        }]
        return sb

    def test_skip_gate_reusa_la_lectura_del_ctx(self):
        """Conv en human_takeover → skip; `conversations` se leyó UNA vez
        (for_gates), no dos (skip gate ya no re-lee)."""
        import agentic.dispatcher as dispatcher_mod

        sb = self._sb("human_takeover")
        _run(dispatcher_mod.dispatch_message(
            sb, message_id="msg-1", tenant_id="t1",
            conversation_id="c1", content="hola", content_type="text",
        ))
        self.assertEqual(sb.select_count("conversations"), 1)
        # El mensaje quedó marcado skipped (comportamiento intacto).
        self.assertTrue(any(
            t == "messages" and f.get("processing_status") == "skipped"
            for t, f in sb.updates
        ))

    def test_path_agentic_recibe_el_ctx_del_turno(self):
        """bot_active → el turno procede y `_run_agentic_full` recibe el
        turn_ctx construido en dispatch_message (misma conversación leída)."""
        import agentic.dispatcher as dispatcher_mod

        sb = self._sb("bot_active")
        with patch.object(dispatcher_mod, "_run_agentic_full",
                          new=AsyncMock()) as mock_agentic, \
             patch.object(dispatcher_mod, "is_tenant_agentic_enabled",
                          new=AsyncMock(return_value=True)):
            _run(dispatcher_mod.dispatch_message(
                sb, message_id="msg-1", tenant_id="t1",
                conversation_id="c1", content="hola", content_type="text",
            ))
        mock_agentic.assert_awaited_once()
        ctx_pasado = mock_agentic.call_args.kwargs.get("turn_ctx")
        self.assertIsNotNone(ctx_pasado)
        self.assertEqual(ctx_pasado.conversation.get("status"), "bot_active")
        self.assertEqual(ctx_pasado.customer_phone, "573001112233")
        self.assertEqual(sb.select_count("conversations"), 1)

    def test_optout_gate_return_true_termina_sin_releer(self):
        """P11: handler procesa opt-out (return True) → el turno termina SIN
        la re-lectura de status que había antes (ni una select extra)."""
        import agentic.dispatcher as dispatcher_mod

        sb = self._sb("bot_active")
        with patch.object(dispatcher_mod, "_handle_optout_if_keyword",
                          new=AsyncMock(return_value=True)) as mock_optout:
            _run(dispatcher_mod.dispatch_message(
                sb, message_id="msg-1", tenant_id="t1",
                conversation_id="c1", content="STOP", content_type="text",
            ))
        mock_optout.assert_awaited_once()
        # Solo la lectura del ctx (for_gates) — ninguna re-lectura post-handler.
        self.assertEqual(sb.select_count("conversations"), 1)


if __name__ == "__main__":
    unittest.main()
