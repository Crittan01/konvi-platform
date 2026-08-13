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
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
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
        self.assertTrue(text)  # tiene contenido degraded natural.
        # Rev. 107: mensaje natural sin delatar bot. "Déjame revisar con
        # mi equipo" + silent escalation. NO debe contener jerga técnica.
        self.assertNotIn("procesando", text.lower())
        self.assertNotIn("error", text.lower())
        # Debe indicar acción (revisar/momento) sin pedir reformular.
        lower = text.lower()
        self.assertTrue(
            "revisar" in lower or "momento" in lower or "equipo" in lower,
            f"esperaba mensaje natural de espera: {text!r}",
        )

    def test_recitation_attempt0_retry_history_10(self):
        text, retry, limit = _recovery_strategy_for_finish_reason("RECITATION", 0)
        self.assertTrue(retry)
        self.assertEqual(limit, 10)

    def test_safety_nunca_retry_mensaje_natural(self):
        """SAFETY siempre degraded — retry no resuelve (mismo input → mismo block).
        Mensaje natural, no robótico."""
        text, retry, _ = _recovery_strategy_for_finish_reason("SAFETY", 0)
        self.assertFalse(retry)
        self.assertIn("cuéntame de otra forma", text.lower())

    def test_blocklist_degraded(self):
        text, retry, _ = _recovery_strategy_for_finish_reason("BLOCKLIST", 0)
        self.assertFalse(retry)
        self.assertIn("de otra forma", text.lower())

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

    def test_stop_attempt0_retry_history_5_rev107(self):
        """Rev. 107: STOP+empty hace 1 retry con history reducido a 5 turns
        antes de degraded. Causa raíz reproducida con conv KAIU bde83d84 y
        phone 573999999999 — saturación prompt+tools hace que Gemini cierre
        con STOP sin emitir parts. Retry con history reducido suele
        resolverlo. Si tras retry sigue empty, ahí sí degraded."""
        text, retry, limit = _recovery_strategy_for_finish_reason("STOP", 0)
        self.assertEqual(text, "")
        self.assertTrue(retry)
        self.assertEqual(limit, 5)

    def test_stop_attempt1_ya_agotado_degraded(self):
        """Tras retry, si sigue STOP empty, degraded natural + sin jerga.
        Rev. 107: mensaje pivot a "déjame revisar" + silent escalation
        (sin pedir reformular, sin "se me cruzó algo")."""
        text, retry, _ = _recovery_strategy_for_finish_reason("STOP", 1)
        self.assertFalse(retry)
        self.assertNotIn("procesando", text.lower())
        self.assertNotIn("se me cruzó", text.lower())
        lower = text.lower()
        self.assertTrue(
            "revisar" in lower or "momento" in lower or "equipo" in lower,
            f"esperaba mensaje natural de espera: {text!r}",
        )

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
