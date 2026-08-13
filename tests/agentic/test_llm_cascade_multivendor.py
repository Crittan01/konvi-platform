"""Tests del cascade multi-vendor (rev. 109 Día 3).

Cubre:
  • Tier promotion tras fail transitorio.
  • Skip Claude tier sin ANTHROPIC_API_KEY.
  • Re-lanzar excepción no-transitoria sin promover.
  • Degraded cuando todos los tiers fallan.
"""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from llm_cascade import cascade_invoke, CascadeOutcome, _vendor_of, _is_transient


class VendorInferenceTests(unittest.TestCase):
    def test_gemini_models(self):
        self.assertEqual(_vendor_of("gemini-3.5-flash"), "gemini")
        self.assertEqual(_vendor_of("gemini-3.1-pro-preview"), "gemini")
        self.assertEqual(_vendor_of("google/gemini-3.5-flash"), "gemini")

    def test_claude_models(self):
        self.assertEqual(_vendor_of("claude-sonnet-4-5"), "anthropic")
        self.assertEqual(_vendor_of("anthropic/claude-opus-4-7"), "anthropic")

    def test_unknown_model_raises(self):
        with self.assertRaises(ValueError):
            _vendor_of("gpt-5-turbo")


class TransientDetectionTests(unittest.TestCase):
    def test_503_detected(self):
        self.assertTrue(_is_transient(Exception("503 Service Unavailable")))

    def test_empty_output_detected(self):
        self.assertTrue(_is_transient("finish=STOP_NO_TEXT empty_output"))

    def test_429_rate_limit(self):
        self.assertTrue(_is_transient("429 rate limit exceeded"))

    def test_schema_error_not_transient(self):
        self.assertFalse(_is_transient("Invalid argument: missing field"))


class CascadeFlowTests(unittest.TestCase):
    def setUp(self):
        # Asegurar que tests no dependan de env real.
        self._env_backup = os.environ.copy()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("LLM_CASCADE_TIERS", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_first_tier_success_short_circuits(self):
        calls = []
        def invoker(model):
            calls.append(model)
            return {"text": f"ok from {model}"}
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite", "gemini-3.5-flash"],
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.model_used, "gemini-3.1-flash-lite")
        self.assertEqual(out.vendor_used, "gemini")
        self.assertEqual(out.tier_index, 0)
        self.assertEqual(out.total_attempts, 1)
        self.assertEqual(calls, ["gemini-3.1-flash-lite"])

    def test_promote_after_transient_fail(self):
        calls = []
        def invoker(model):
            calls.append(model)
            if model == "gemini-3.1-flash-lite":
                raise Exception("503 Service Unavailable")
            return {"text": "ok from flash"}
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite", "gemini-3.5-flash"],
            attempts_per_tier=2,
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.model_used, "gemini-3.5-flash")
        self.assertEqual(out.tier_index, 1)
        # 2 intentos en tier 0 (Flash Lite) + 1 en tier 1 (Flash).
        self.assertEqual(out.total_attempts, 3)
        self.assertEqual(calls, [
            "gemini-3.1-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
        ])

    def test_skip_claude_tier_without_api_key(self):
        """Sin ANTHROPIC_API_KEY, Claude tier se omite silenciosamente."""
        calls = []
        def gemini_invoker(model):
            calls.append(model)
            raise Exception("503 Service Unavailable")
        claude_called = [False]
        def claude_invoker():
            claude_called[0] = True
            return {"text": "claude rescue"}
        out = cascade_invoke(
            gemini_invoker=gemini_invoker,
            claude_invoker=claude_invoker,
            tiers=["gemini-3.1-flash-lite", "claude-sonnet-4-5"],
            attempts_per_tier=1,
            sleep_fn=lambda _s: None,
        )
        # Claude no se llamó porque no hay API key.
        self.assertFalse(claude_called[0])
        # Cascade degraded.
        self.assertTrue(out.degraded)

    def test_claude_tier_invoked_with_api_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        calls = []
        def gemini_invoker(model):
            calls.append(model)
            raise Exception("503 Service Unavailable")
        def claude_invoker():
            return {"text": "claude rescue success"}
        out = cascade_invoke(
            gemini_invoker=gemini_invoker,
            claude_invoker=claude_invoker,
            tiers=["gemini-3.1-flash-lite", "claude-sonnet-4-5"],
            attempts_per_tier=1,
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.vendor_used, "anthropic")
        self.assertEqual(out.model_used, "claude-sonnet-4-5")

    def test_non_transient_error_reraises(self):
        def invoker(model):
            raise ValueError("Invalid schema: missing field")
        with self.assertRaises(ValueError):
            cascade_invoke(
                gemini_invoker=invoker,
                tiers=["gemini-3.5-flash"],
                sleep_fn=lambda _s: None,
            )

    def test_all_tiers_fail_returns_degraded(self):
        def invoker(model):
            raise Exception("503 Service Unavailable")
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-pro-preview"],
            attempts_per_tier=1,
            sleep_fn=lambda _s: None,
        )
        self.assertTrue(out.degraded)
        self.assertEqual(out.total_attempts, 3)
        self.assertIn("Service Unavailable", out.last_error or "")
        self.assertEqual(out.tiers_tried, [
            "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-pro-preview",
        ])


if __name__ == "__main__":
    unittest.main()
