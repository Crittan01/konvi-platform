"""Certificación F5 bot_engine — guardrails tenant, content_type no-texto,
telemetría total_tokens y rate-limit inbound→LLM.

Cubre las unidades puras/deterministas de las decisiones bot_engine:
  #1 onboarding agentic (migración — no testeable en pytest, ver .sql)
  #2 total_tokens (extractor Gemini usage_metadata)
  #3 content_type document/sticker/location (handle_nontext_content)
  + guardrails tenant (parse/apply/is_state_denied)
  + rate-limit inbound→LLM (helper del worker, fail-open/cap-off)
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.nontext_content import (
    handle_nontext_content,
    NonTextResponse,
    NONTEXT_CONTENT_TYPES,
)
from agentic.tenant_guardrails import (
    parse_tenant_guardrails,
    apply_tenant_tool_guardrails,
    is_state_denied,
)
from agentic.agent import _extract_total_tokens


# ─── #3 content_type no-texto/no-multimodal ────────────────────────────────
class NonTextContentTests(unittest.TestCase):
    def test_document_escalates_to_human(self):
        r = handle_nontext_content("document")
        self.assertIsInstance(r, NonTextResponse)
        self.assertTrue(r.escalate)
        self.assertTrue(r.reply_text)
        self.assertIsNotNone(r.escalation_reason)

    def test_location_asks_text_no_escalation(self):
        r = handle_nontext_content("location")
        self.assertIsNotNone(r)
        self.assertFalse(r.escalate)
        self.assertIn("ciudad", r.reply_text.lower())

    def test_sticker_friendly_no_escalation(self):
        r = handle_nontext_content("sticker")
        self.assertIsNotNone(r)
        self.assertFalse(r.escalate)
        self.assertTrue(r.reply_text)

    def test_case_insensitive(self):
        self.assertTrue(handle_nontext_content("DOCUMENT").escalate)

    def test_text_and_multimodal_return_none(self):
        # texto y los tipos multimodal NO los gobierna este módulo.
        for ct in ("text", "audio", "image", "video", "interactive", "button"):
            self.assertIsNone(handle_nontext_content(ct), ct)

    def test_constant_matches_handled_types(self):
        self.assertEqual(NONTEXT_CONTENT_TYPES, frozenset({"document", "sticker", "location"}))
        for ct in NONTEXT_CONTENT_TYPES:
            self.assertIsNotNone(handle_nontext_content(ct))


# ─── #2 telemetría total_tokens ────────────────────────────────────────────
class TotalTokensExtractorTests(unittest.TestCase):
    def _resp(self, total):
        usage = types.SimpleNamespace(total_token_count=total)
        return types.SimpleNamespace(usage_metadata=usage)

    def test_extracts_count(self):
        self.assertEqual(_extract_total_tokens(self._resp(1234)), 1234)

    def test_no_usage_metadata_zero(self):
        self.assertEqual(_extract_total_tokens(types.SimpleNamespace()), 0)

    def test_none_response_zero(self):
        self.assertEqual(_extract_total_tokens(None), 0)

    def test_none_count_zero(self):
        self.assertEqual(_extract_total_tokens(self._resp(None)), 0)


# ─── guardrails a nivel tenant ─────────────────────────────────────────────
class TenantGuardrailsParseTests(unittest.TestCase):
    def test_empty_meta(self):
        g = parse_tenant_guardrails({})
        self.assertEqual(g["tools_allowed"], set())
        self.assertEqual(g["tools_denied"], set())
        self.assertEqual(g["fsm_states_denied"], set())

    def test_none_meta(self):
        self.assertEqual(parse_tenant_guardrails(None)["tools_denied"], set())

    def test_parses_lists(self):
        g = parse_tenant_guardrails({"guardrails": {
            "tools_allowed": ["a", "b"],
            "tools_denied": ["c"],
            "fsm_states_denied": ["post_payment"],
        }})
        self.assertEqual(g["tools_allowed"], {"a", "b"})
        self.assertEqual(g["tools_denied"], {"c"})
        self.assertEqual(g["fsm_states_denied"], {"POST_PAYMENT"})

    def test_garbage_degrades(self):
        g = parse_tenant_guardrails({"guardrails": {"tools_denied": "notalist"}})
        self.assertEqual(g["tools_denied"], set())


class TenantGuardrailsApplyTests(unittest.TestCase):
    def test_no_config_is_noop(self):
        g = parse_tenant_guardrails({})
        self.assertEqual(apply_tenant_tool_guardrails({"a", "b"}, g), {"a", "b"})
        self.assertIsNone(apply_tenant_tool_guardrails(None, g))

    def test_denylist_restricts(self):
        g = parse_tenant_guardrails({"guardrails": {"tools_denied": ["b"]}})
        self.assertEqual(apply_tenant_tool_guardrails({"a", "b", "c"}, g), {"a", "c"})

    def test_allowlist_intersects(self):
        g = parse_tenant_guardrails({"guardrails": {"tools_allowed": ["a", "z"]}})
        self.assertEqual(apply_tenant_tool_guardrails({"a", "b", "c"}, g), {"a"})

    def test_never_expands(self):
        # allowlist NO agrega tools que el per-state no permitió.
        g = parse_tenant_guardrails({"guardrails": {"tools_allowed": ["a", "x"]}})
        out = apply_tenant_tool_guardrails({"a"}, g)
        self.assertEqual(out, {"a"})
        self.assertNotIn("x", out)

    def test_monolito_none_materializes_universe(self):
        g = parse_tenant_guardrails({"guardrails": {"tools_denied": ["b"]}})
        out = apply_tenant_tool_guardrails(None, g, all_tool_names=["a", "b", "c"])
        self.assertEqual(out, {"a", "c"})

    def test_monolito_none_without_universe_is_noop(self):
        g = parse_tenant_guardrails({"guardrails": {"tools_denied": ["b"]}})
        self.assertIsNone(apply_tenant_tool_guardrails(None, g))

    def test_allow_then_deny_order(self):
        g = parse_tenant_guardrails({"guardrails": {
            "tools_allowed": ["a", "b"], "tools_denied": ["b"],
        }})
        self.assertEqual(apply_tenant_tool_guardrails({"a", "b", "c"}, g), {"a"})


class StateDeniedTests(unittest.TestCase):
    def test_denied(self):
        g = parse_tenant_guardrails({"guardrails": {"fsm_states_denied": ["POST_PAYMENT"]}})
        self.assertTrue(is_state_denied(g, "post_payment"))
        self.assertTrue(is_state_denied(g, "POST_PAYMENT"))

    def test_not_denied(self):
        g = parse_tenant_guardrails({"guardrails": {"fsm_states_denied": ["POST_PAYMENT"]}})
        self.assertFalse(is_state_denied(g, "browsing"))
        self.assertFalse(is_state_denied(g, None))


# ─── rate-limit inbound→LLM (worker helper) ────────────────────────────────
class InboundRateLimitTests(unittest.TestCase):
    def _worker_with_rpc(self, allowed):
        import worker as _w

        class _RpcResult:
            data = [{"allowed": allowed, "remaining": 0, "reset_in": 30}]

        class _Supabase:
            def rpc(self, name, params):
                assert name == "rate_limit_hit"
                return types.SimpleNamespace(execute=lambda: _RpcResult())

        inst = _w.OrchestratorWorker.__new__(_w.OrchestratorWorker)
        inst.supabase = _Supabase()
        return _w, inst

    def test_allowed_not_limited(self):
        w, inst = self._worker_with_rpc(allowed=True)
        orig = w.INBOUND_LLM_RATE_LIMIT
        w.INBOUND_LLM_RATE_LIMIT = 30
        try:
            self.assertFalse(inst._inbound_llm_rate_limited("t", "c"))
        finally:
            w.INBOUND_LLM_RATE_LIMIT = orig

    def test_over_limit_is_limited(self):
        w, inst = self._worker_with_rpc(allowed=False)
        orig = w.INBOUND_LLM_RATE_LIMIT
        w.INBOUND_LLM_RATE_LIMIT = 30
        try:
            self.assertTrue(inst._inbound_llm_rate_limited("t", "c"))
        finally:
            w.INBOUND_LLM_RATE_LIMIT = orig

    def test_cap_zero_disables(self):
        import worker as _w
        inst = _w.OrchestratorWorker.__new__(_w.OrchestratorWorker)
        inst.supabase = None  # no debe tocarse cuando el cap está en 0
        orig = _w.INBOUND_LLM_RATE_LIMIT
        _w.INBOUND_LLM_RATE_LIMIT = 0
        try:
            self.assertFalse(inst._inbound_llm_rate_limited("t", "c"))
        finally:
            _w.INBOUND_LLM_RATE_LIMIT = orig

    def test_rpc_error_fail_open(self):
        import worker as _w

        class _Boom:
            def rpc(self, *a, **k):
                raise RuntimeError("db down")

        inst = _w.OrchestratorWorker.__new__(_w.OrchestratorWorker)
        inst.supabase = _Boom()
        orig = _w.INBOUND_LLM_RATE_LIMIT
        _w.INBOUND_LLM_RATE_LIMIT = 30
        try:
            self.assertFalse(inst._inbound_llm_rate_limited("t", "c"))
        finally:
            _w.INBOUND_LLM_RATE_LIMIT = orig


if __name__ == "__main__":
    unittest.main()
