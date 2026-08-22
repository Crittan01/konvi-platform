"""B-1 — tests del resumen rodante de conversación (memoria fuera de ventana).

Auditoría bot 2026-08-21: ventana de 25 mensajes SIN resumen → amnesia
estructural; el retry por empty_output cortaba a 5 mensajes (amnesia total).

Cobertura:
  • _build_gemini_messages: el resumen se inyecta como PRIMER content (role
    user, prefijo canónico) y el resto de la ventana queda intacta.
  • _trim_messages_for_retry: el bloque de resumen sobrevive al corte a N.
  • summary_text_for_prompt: extracción + tope de caracteres.
  • maybe_update_conversation_summary: histeresis (sin resumen si la conv no
    supera la ventana; primera regeneración; <K nuevos → no-op; LLM caído →
    no persiste) + persistencia con cursor covers_until.
  • fetch_summary_text: devuelve texto o None (error → None, fail-open).
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.agent import _build_gemini_messages, _trim_messages_for_retry  # noqa: E402
from agentic.conversation_summary import (  # noqa: E402
    SUMMARY_PROMPT_PREFIX,
    build_summary_message,
    fetch_summary_text,
    is_summary_message,
    maybe_update_conversation_summary,
    summary_text_for_prompt,
)


class BuildGeminiMessagesSummaryTests(unittest.TestCase):

    def test_summary_is_first_content(self):
        msgs = _build_gemini_messages(
            [{"direction": "inbound", "content": "hola"}],
            "y el total?",
            conversation_summary="El cliente pidió 2 jabones de coco y envío a Bogotá.",
        )
        self.assertEqual(msgs[0]["role"], "user")
        text = msgs[0]["parts"][0]["text"]
        self.assertTrue(text.startswith(SUMMARY_PROMPT_PREFIX))
        self.assertIn("2 jabones de coco", text)
        # La ventana cruda queda intacta después del bloque.
        self.assertEqual(msgs[1]["parts"][0]["text"], "hola")
        self.assertEqual(msgs[-1]["parts"][0]["text"], "y el total?")

    def test_no_summary_no_block(self):
        msgs = _build_gemini_messages(
            [{"direction": "inbound", "content": "hola"}], "siguiente",
        )
        self.assertEqual(msgs[0]["parts"][0]["text"], "hola")

    def test_summary_block_detected_by_is_summary_message(self):
        block = build_summary_message("resumen X")
        self.assertTrue(is_summary_message(block))
        self.assertFalse(is_summary_message({"role": "user", "parts": [{"text": "hola"}]}))
        self.assertFalse(is_summary_message({}))


class TrimRetryTests(unittest.TestCase):

    def _msgs(self, n, with_summary=True):
        out = []
        if with_summary:
            out.append(build_summary_message("memoria compactada"))
        out += [
            {"role": "user" if i % 2 == 0 else "model", "parts": [{"text": f"m{i}"}]}
            for i in range(n)
        ]
        return out

    def test_retry_preserves_summary_block(self):
        msgs = self._msgs(20, with_summary=True)
        trimmed = _trim_messages_for_retry(msgs, 5)
        self.assertTrue(is_summary_message(trimmed[0]))
        self.assertEqual(len(trimmed), 6)  # resumen + 5 recientes
        self.assertEqual(trimmed[-1]["parts"][0]["text"], "m19")

    def test_retry_without_summary_unchanged_behavior(self):
        msgs = self._msgs(20, with_summary=False)
        trimmed = _trim_messages_for_retry(msgs, 5)
        self.assertEqual(len(trimmed), 5)
        self.assertEqual(trimmed[0]["parts"][0]["text"], "m15")

    def test_short_list_untouched(self):
        msgs = self._msgs(3)
        self.assertEqual(_trim_messages_for_retry(msgs, 5), msgs)

    def test_zero_limit_untouched(self):
        msgs = self._msgs(10)
        self.assertEqual(_trim_messages_for_retry(msgs, 0), msgs)


class SummaryTextTests(unittest.TestCase):

    def test_extracts_text(self):
        self.assertEqual(
            summary_text_for_prompt({"text": "memoria"}), "memoria",
        )

    def test_missing_or_invalid_returns_none(self):
        self.assertIsNone(summary_text_for_prompt(None))
        self.assertIsNone(summary_text_for_prompt({}))
        self.assertIsNone(summary_text_for_prompt({"text": "  "}))
        self.assertIsNone(summary_text_for_prompt("no-es-dict"))

    def test_truncates_to_max_chars(self):
        from agentic.conversation_summary import SUMMARY_MAX_CHARS
        text = summary_text_for_prompt({"text": "x" * (SUMMARY_MAX_CHARS + 100)})
        self.assertEqual(len(text), SUMMARY_MAX_CHARS)


# ─── maybe_update_conversation_summary ───────────────────────────────────────

def _sb_conv(*, total_msgs, summary=None, edge="2026-08-22T10:00:00", fold_rows=None):
    """Supabase mock enrutado por tabla/query de la función (refs estables)."""
    sb = MagicMock()
    conv_q = MagicMock(name="conv_q")
    msg_q = MagicMock(name="msg_q")

    conv_q.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"conversation_summary": summary or {}}],
    )
    conv_q.update.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])

    # count total (head=True)
    msg_q.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        count=total_msgs, data=[],
    )
    # edge (order desc + range)
    msg_q.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.range.return_value.execute.return_value = SimpleNamespace(
        data=[{"created_at": edge}],
    )
    # fold rows (lt + order asc, opcional gt covers)
    fold_chain = msg_q.select.return_value.eq.return_value.eq.return_value.lt.return_value.order.return_value
    fold_chain.limit.return_value.execute.return_value = SimpleNamespace(
        data=fold_rows or [],
    )
    fold_chain.gt.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=fold_rows or [],
    )

    def _table(name):
        return conv_q if name == "conversations" else msg_q

    sb.table.side_effect = _table
    sb._conv_q = conv_q
    return sb


def _rows(n):
    return [
        {"direction": "inbound" if i % 2 == 0 else "outbound", "content": f"m{i}"}
        for i in range(n)
    ]


class MaybeUpdateSummaryTests(unittest.IsolatedAsyncioTestCase):

    async def test_below_window_is_noop(self):
        sb = _sb_conv(total_msgs=20)
        with patch("agentic.conversation_summary._summarize_with_llm",
                   new=AsyncMock(return_value="resumen")) as llm:
            await maybe_update_conversation_summary(
                sb, tenant_id="t1", conversation_id="c1", history_limit=25,
            )
        llm.assert_not_awaited()

    async def test_first_summary_generates_and_persists(self):
        sb = _sb_conv(total_msgs=40, summary=None, fold_rows=_rows(12))
        with patch("agentic.conversation_summary._summarize_with_llm",
                   new=AsyncMock(return_value="Cliente pidió 2 jabones, envío a Bogotá.")) as llm:
            await maybe_update_conversation_summary(
                sb, tenant_id="t1", conversation_id="c1", history_limit=25,
            )
        llm.assert_awaited_once()
        update_payload = sb._conv_q.update.call_args.args[0]
        summary = update_payload["conversation_summary"]
        self.assertIn("2 jabones", summary["text"])
        self.assertEqual(summary["covers_until_created_at"], "2026-08-22T10:00:00")
        self.assertEqual(summary["message_count"], 40)

    async def test_below_hysteresis_threshold_is_noop(self):
        sb = _sb_conv(
            total_msgs=40,
            summary={"text": "prev", "covers_until_created_at": "2026-08-22T08:00:00"},
            fold_rows=_rows(3),  # < SUMMARY_REGEN_MIN_NEW (10)
        )
        with patch("agentic.conversation_summary._summarize_with_llm",
                   new=AsyncMock(return_value="nuevo")) as llm:
            await maybe_update_conversation_summary(
                sb, tenant_id="t1", conversation_id="c1", history_limit=25,
            )
        llm.assert_not_awaited()

    async def test_llm_failure_does_not_persist(self):
        sb = _sb_conv(total_msgs=40, summary=None, fold_rows=_rows(12))
        with patch("agentic.conversation_summary._summarize_with_llm",
                   new=AsyncMock(return_value=None)):
            await maybe_update_conversation_summary(
                sb, tenant_id="t1", conversation_id="c1", history_limit=25,
            )
        sb.table("conversations").update.assert_not_called()

    async def test_db_error_never_raises(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("DB down")
        await maybe_update_conversation_summary(
            sb, tenant_id="t1", conversation_id="c1", history_limit=25,
        )  # no exception


class FetchSummaryTests(unittest.IsolatedAsyncioTestCase):

    async def test_returns_text(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"conversation_summary": {"text": "memoria útil"}}],
        )
        text = await fetch_summary_text(sb, tenant_id="t1", conversation_id="c1")
        self.assertEqual(text, "memoria útil")

    async def test_error_returns_none(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("DB down")
        text = await fetch_summary_text(sb, tenant_id="t1", conversation_id="c1")
        self.assertIsNone(text)


if __name__ == "__main__":
    unittest.main()
