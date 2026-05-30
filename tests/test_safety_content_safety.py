"""Tests del safety/content_safety (rev. 104, F1-1 batch 2)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "services/ai-orchestrator/safety/content_safety.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_safety_content_under_test", str(PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MentalHealthCrisisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_explicit_crisis_phrases_trigger(self):
        for q in (
            "Me quiero matar",
            "Voy a suicidarme hoy",
            "no quiero vivir más",
            "tengo pensamientos suicidas",
            "ya no aguanto más",
        ):
            self.assertTrue(self.mod.detect_mental_health_crisis(q),
                            f"esperaba True para {q!r}")

    def test_neutral_no_trigger(self):
        for q in (
            "Quiero comprar un jabón",
            "Hola, ¿cómo estás?",
            "El producto cuesta mucho",
        ):
            self.assertFalse(self.mod.detect_mental_health_crisis(q))

    def test_empty(self):
        self.assertFalse(self.mod.detect_mental_health_crisis(""))
        self.assertFalse(self.mod.detect_mental_health_crisis(None))


class SensitivePaymentDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_cvv_detected(self):
        for q in (
            "mi cvv es 123",
            "CVV: 4567",
            "el código de seguridad es 999",
            "cvc 200",
        ):
            ok, reason = self.mod.detect_sensitive_payment_data(q)
            self.assertTrue(ok, f"esperaba True para {q!r}")
            self.assertEqual(reason, "cvv_detected")

    def test_credit_card_detected(self):
        for q in (
            "tarjeta 4111111111111111",
            "es 4111-1111-1111-1111",
            "5500 0000 0000 0004",
        ):
            ok, reason = self.mod.detect_sensitive_payment_data(q)
            self.assertTrue(ok, f"esperaba True para {q!r}")
            self.assertEqual(reason, "credit_card_pattern")

    def test_cedula_no_trigger(self):
        # Cédulas colombianas (8-12 dígitos) NO deben gatillar.
        for q in (
            "mi cédula es 1032414179",  # 10 dígitos
            "cc 12345678",               # 8 dígitos
            "documento 123456789012",    # 12 dígitos
        ):
            ok, reason = self.mod.detect_sensitive_payment_data(q)
            self.assertFalse(ok, f"esperaba False para cédula {q!r}: got {reason}")

    def test_neutral_no_trigger(self):
        for q in (
            "Hola, ¿cuánto cuesta?",
            "envío a Bogotá",
            "el total es $25.000",
        ):
            ok, _ = self.mod.detect_sensitive_payment_data(q)
            self.assertFalse(ok)

    def test_empty(self):
        ok, reason = self.mod.detect_sensitive_payment_data("")
        self.assertFalse(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
