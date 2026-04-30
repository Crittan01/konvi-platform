"""Rev. 84 — Tests de guardrails de cumplimiento Meta Business Policy.

Cita oficial (https://business.whatsapp.com/policy):
  • Healthcare: telemedicina y datos de salud prohibidos sin sistema cumpliendo.
  • Personal data: no recolectar números completos de tarjeta, banco, ID.

Detectores PRE-LLM determinísticos para garantizar cumplimiento sin
depender de la disciplina del modelo.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _detect_mental_health_crisis,
    _detect_sensitive_payment_data,
)


class MentalHealthCrisisDetectorTests(unittest.TestCase):
    """P0 — escalación inmediata a humano."""

    def test_explicit_suicide(self):
        self.assertTrue(_detect_mental_health_crisis("Me quiero matar"))

    def test_self_harm(self):
        self.assertTrue(_detect_mental_health_crisis("Quiero hacerme daño"))

    def test_no_quiero_vivir(self):
        self.assertTrue(_detect_mental_health_crisis("ya no quiero vivir"))

    def test_acabar_con_mi_vida(self):
        self.assertTrue(_detect_mental_health_crisis("voy a acabar con mi vida"))

    def test_with_accent(self):
        self.assertTrue(_detect_mental_health_crisis("Me quiero hacer daño"))

    def test_normal_question_NOT_crisis(self):
        self.assertFalse(_detect_mental_health_crisis("¿Cuánto cuesta el jabón?"))

    def test_complaint_NOT_crisis(self):
        self.assertFalse(_detect_mental_health_crisis("Estoy molesto con el envío"))

    def test_empty(self):
        self.assertFalse(_detect_mental_health_crisis(""))


class SensitivePaymentDataDetectorTests(unittest.TestCase):
    """PCI — no procesar datos de tarjeta en chat."""

    def test_credit_card_16_digits(self):
        is_sensitive, reason = _detect_sensitive_payment_data(
            "mi tarjeta es 4532015112830366"
        )
        self.assertTrue(is_sensitive)

    def test_credit_card_with_spaces(self):
        is_sensitive, _ = _detect_sensitive_payment_data(
            "tarjeta 4532 0151 1283 0366 vencimiento 12/28"
        )
        self.assertTrue(is_sensitive)

    def test_credit_card_with_hyphens(self):
        is_sensitive, _ = _detect_sensitive_payment_data(
            "4532-0151-1283-0366"
        )
        self.assertTrue(is_sensitive)

    def test_cvv_explicit(self):
        is_sensitive, reason = _detect_sensitive_payment_data(
            "el cvv es 123"
        )
        self.assertTrue(is_sensitive)
        self.assertEqual(reason, "cvv_detected")

    def test_codigo_de_seguridad(self):
        is_sensitive, _ = _detect_sensitive_payment_data(
            "código de seguridad: 456"
        )
        self.assertTrue(is_sensitive)

    def test_cedula_NOT_sensitive(self):
        # CC colombiana = 8-10 dígitos, NO debe gatillar credit card detector.
        is_sensitive, _ = _detect_sensitive_payment_data(
            "mi cédula es 1032414179"
        )
        self.assertFalse(is_sensitive)

    def test_phone_NOT_sensitive(self):
        is_sensitive, _ = _detect_sensitive_payment_data(
            "mi celular es +573125835649"
        )
        self.assertFalse(is_sensitive)

    def test_normal_text(self):
        is_sensitive, _ = _detect_sensitive_payment_data(
            "Hola, quiero comprar un jabón"
        )
        self.assertFalse(is_sensitive)

    def test_empty(self):
        is_sensitive, _ = _detect_sensitive_payment_data("")
        self.assertFalse(is_sensitive)


class FalsePositiveBoundaryTests(unittest.TestCase):
    """Sanity: detectores no deben gatillar en mensajes legítimos."""

    def test_dolor_de_cabeza_NOT_crisis(self):
        # Pregunta médica menor, NO crisis suicida — el detector solo
        # gatilla en ideación clara.
        self.assertFalse(_detect_mental_health_crisis(
            "Tengo dolor de cabeza, ¿qué jabón me recomiendas?"
        ))

    def test_long_doc_number_below_13_NOT_card(self):
        # 12 dígitos consecutivos ≠ tarjeta (cédula extranjera, ID raro)
        is_sensitive, _ = _detect_sensitive_payment_data(
            "mi documento es 123456789012"
        )
        self.assertFalse(is_sensitive)


if __name__ == "__main__":
    unittest.main()
