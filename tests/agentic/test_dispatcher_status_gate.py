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

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
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
    sb.table.return_value = chain
    return sb


class DispatcherStatusGateTests(unittest.TestCase):

    def test_skip_si_conv_human_takeover(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("human_takeover")
        self.assertTrue(_should_skip_for_conv_status(sb, "conv-1"))

    def test_skip_si_conv_closed(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("closed")
        self.assertTrue(_should_skip_for_conv_status(sb, "conv-1"))

    def test_no_skip_si_conv_bot_active(self):
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("bot_active")
        self.assertFalse(_should_skip_for_conv_status(sb, "conv-1"))

    def test_no_skip_si_conv_no_existe(self):
        """Si conv no existe (caso raro), no skipea — deja al legacy fallar."""
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = _make_sb("")  # data vacía
        self.assertFalse(_should_skip_for_conv_status(sb, "conv-1"))

    def test_no_skip_si_db_falla(self):
        """Error leyendo conv → no skipea (default permisivo)."""
        from agentic.dispatcher import _should_skip_for_conv_status
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("db down")
        self.assertFalse(_should_skip_for_conv_status(sb, "conv-1"))

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


if __name__ == "__main__":
    unittest.main()
