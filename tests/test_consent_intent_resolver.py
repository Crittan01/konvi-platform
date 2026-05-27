"""Tests para consent_intent_resolver — rev. 108 fix arquitectónico."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from agentic.consent_intent_resolver import detect_consent_intent


_BOT_ASKED = "Me autorizas a usar tus datos personales para el envío?"
_BOT_NOT_ASKED = "Hola! Cómo estás?"


class DetectConsentGrantedTests(unittest.TestCase):

    def test_simple_si(self):
        r = detect_consent_intent("Sí", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_si_acepto(self):
        r = detect_consent_intent("Sí, acepto", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_acepto_solo(self):
        r = detect_consent_intent("Acepto", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_de_acuerdo(self):
        r = detect_consent_intent("Estoy de acuerdo", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_ok(self):
        r = detect_consent_intent("OK", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_dale_colombia(self):
        r = detect_consent_intent("Dale", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")

    def test_autorizo(self):
        r = detect_consent_intent("Te autorizo a usar mis datos", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_granted")


class DetectConsentDeniedTests(unittest.TestCase):

    def test_simple_no(self):
        r = detect_consent_intent("No", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_denied")

    def test_no_acepto(self):
        r = detect_consent_intent("No acepto", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_denied")

    def test_no_autorizo(self):
        r = detect_consent_intent("No te autorizo", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_denied")

    def test_rechazo(self):
        r = detect_consent_intent("Rechazo", _BOT_ASKED)
        self.assertEqual(r["intent"], "consent_denied")


class ContextRequiredTests(unittest.TestCase):
    """Si bot NO pidió consent en su mensaje anterior, NO aplica."""

    def test_si_pero_bot_saludo(self):
        # Cliente dice "Sí" pero el bot solo saludó — no es consent.
        r = detect_consent_intent("Sí", _BOT_NOT_ASKED)
        self.assertIsNone(r)

    def test_acepto_pero_bot_saludo(self):
        r = detect_consent_intent("Acepto", _BOT_NOT_ASKED)
        self.assertIsNone(r)

    def test_si_sin_contexto(self):
        # Sin bot_last_outbound, assumes context valid (caller responsib.).
        r = detect_consent_intent("Sí")
        self.assertIsNotNone(r)
        self.assertEqual(r["intent"], "consent_granted")


class NoiseTests(unittest.TestCase):

    def test_empty(self):
        self.assertIsNone(detect_consent_intent("", _BOT_ASKED))

    def test_none_input(self):
        self.assertIsNone(detect_consent_intent(None, _BOT_ASKED))  # type: ignore

    def test_random_text(self):
        self.assertIsNone(
            detect_consent_intent("cuándo llega mi pedido?", _BOT_ASKED),
        )

    def test_si_pero_no_complete(self):
        # "Si me das información..." no es afirmación de consent.
        r = detect_consent_intent("Si me das info", _BOT_ASKED)
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
