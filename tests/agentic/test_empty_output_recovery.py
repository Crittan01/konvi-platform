"""Tests del manejo activo de empty_output (rev. 107).

Antes: el agentic levantaba RuntimeError('agentic_failed: empty_output')
cuando Gemini retornaba candidate sin parts. Eso causaba [ERROR] en logs
+ fallback ciego a legacy.

Ahora: detecta `finish_reason` y aplica strategy:
  • MAX_TOKENS → retry con history reducido a 5 turns.
  • RECITATION → retry con history reducido a 10 turns.
  • MALFORMED_FUNCTION_CALL → retry con history 5.
  • SAFETY / BLOCKLIST / PROHIBITED_CONTENT / SPII → degraded determinístico.
  • STOP/OTHER/UNKNOWN → degraded genérico.

NO levanta excepción. Cliente recibe respuesta válida (recovered o degraded).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.agent import _recovery_strategy_for_finish_reason


class RecoveryStrategyTests(unittest.TestCase):
    """Unit tests puros de la función de decisión por finish_reason."""

    def test_max_tokens_attempt0_retry_con_history_5(self):
        text, retry, limit = _recovery_strategy_for_finish_reason("MAX_TOKENS", 0)
        self.assertEqual(text, "")
        self.assertTrue(retry)
        self.assertEqual(limit, 5)

    def test_max_tokens_attempt1_ya_agotado_degraded(self):
        """Solo 1 retry permitido — al 2do empty con MAX_TOKENS, degraded."""
        text, retry, _ = _recovery_strategy_for_finish_reason("MAX_TOKENS", 1)
        self.assertFalse(retry)
        self.assertTrue(text)  # tiene contenido degraded
        # Cae a strategy default ('STOP/OTHER' degraded genérico).
        self.assertIn("repetírmelo", text.lower())

    def test_recitation_attempt0_retry_history_10(self):
        text, retry, limit = _recovery_strategy_for_finish_reason("RECITATION", 0)
        self.assertTrue(retry)
        self.assertEqual(limit, 10)

    def test_safety_nunca_retry_mensaje_cordial(self):
        """SAFETY siempre degraded — retry no resuelve (mismo input → mismo block)."""
        text, retry, _ = _recovery_strategy_for_finish_reason("SAFETY", 0)
        self.assertFalse(retry)
        self.assertIn("no puedo responder", text.lower())

    def test_blocklist_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("BLOCKLIST", 0)
        self.assertFalse(retry)
        self.assertIn("reformularlo", text.lower())

    def test_prohibited_content_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("PROHIBITED_CONTENT", 0)
        self.assertFalse(retry)
        self.assertTrue(text)

    def test_spii_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("SPII", 0)
        self.assertFalse(retry)
        self.assertTrue(text)

    def test_malformed_function_call_retry(self):
        text, retry, limit = _recovery_strategy_for_finish_reason(
            "MALFORMED_FUNCTION_CALL", 0,
        )
        self.assertTrue(retry)
        self.assertEqual(limit, 5)

    def test_stop_con_parts_vacio_degraded_generico(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("STOP", 0)
        self.assertFalse(retry)
        self.assertIn("repetírmelo", text.lower())

    def test_unknown_finish_reason_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("", 0)
        self.assertFalse(retry)
        self.assertTrue(text)

    def test_other_finish_reason_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("OTHER", 0)
        self.assertFalse(retry)
        self.assertTrue(text)


class ExtractFinishReasonTests(unittest.TestCase):

    def test_extract_finish_reason_de_enum(self):
        from agentic.agent import _extract_finish_reason

        class FakeFinishReason:
            name = "MAX_TOKENS"

        class FakeCandidate:
            finish_reason = FakeFinishReason()
            content = None

        class FakeResp:
            candidates = [FakeCandidate()]

        self.assertEqual(_extract_finish_reason(FakeResp()), "MAX_TOKENS")

    def test_extract_finish_reason_de_string(self):
        from agentic.agent import _extract_finish_reason

        class FakeCandidate:
            finish_reason = "safety"
            content = None

        class FakeResp:
            candidates = [FakeCandidate()]

        self.assertEqual(_extract_finish_reason(FakeResp()), "SAFETY")

    def test_extract_finish_reason_sin_candidates(self):
        from agentic.agent import _extract_finish_reason

        class FakeResp:
            candidates = []

        self.assertEqual(_extract_finish_reason(FakeResp()), "")

    def test_extract_finish_reason_none_response(self):
        from agentic.agent import _extract_finish_reason
        self.assertEqual(_extract_finish_reason(None), "")


if __name__ == "__main__":
    unittest.main()
