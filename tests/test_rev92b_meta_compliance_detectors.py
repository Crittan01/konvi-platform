"""Rev. 92.b — Tests de detectores Meta Business Policy / Commerce Policy.

Cobertura:
  • Healthcare/Telemedicina: Meta prohíbe diagnósticos médicos en
    WhatsApp Business. Bot redirige a profesional médico.
  • Drugs/Pharmaceuticals: Meta Commerce Policy prohíbe venta de Rx y
    OTC en WhatsApp. Bot rechaza cordialmente.

Diseño multi-tenant: detectores y respuestas son vertical-agnósticos.
Ningún tenant puede dar consejo médico ni vender medicamentos por
WhatsApp, sin importar si vende cosmética, tecnología, comida, etc.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _detect_medical_query,
    _detect_drug_purchase_request,
)


class MedicalQueryDetectorTests(unittest.TestCase):
    """Consultas médicas / diagnósticas que el bot debe rechazar."""

    def test_disease_name_query(self):
        cases = [
            "¿Tu producto cura el acné?",
            "Tengo psoriasis, ¿sirve?",
            "¿Es bueno para la dermatitis?",
            "¿Tu jabón trata mi eczema?",
            "Tengo rosácea, ¿qué me recomiendas?",
            "Tengo alergia al níquel",
        ]
        for c in cases:
            self.assertTrue(_detect_medical_query(c), f"falló: {c!r}")

    def test_pregnancy_lactation(self):
        cases = [
            "¿Es seguro en embarazo?",
            "Estoy embarazada, ¿puedo usarlo?",
            "Estoy en lactancia, ¿hay riesgo?",
            "¿Puedo amamantar usando esto?",
        ]
        for c in cases:
            self.assertTrue(_detect_medical_query(c), f"falló: {c!r}")

    def test_diagnosis_intent(self):
        cases = [
            "¿Qué enfermedad tengo?",
            "Necesito diagnóstico de mi piel",
            "Tengo estos síntomas, ¿qué tengo?",
        ]
        for c in cases:
            self.assertTrue(_detect_medical_query(c), f"falló: {c!r}")

    def test_treatment_query(self):
        cases = [
            "¿Qué tratamiento para la caspa?",
            "Sirve para tratar el hongo",
            "Remedio para el dolor de cabeza",
        ]
        for c in cases:
            self.assertTrue(_detect_medical_query(c), f"falló: {c!r}")

    def test_safe_cosmetic_questions_pass_through(self):
        # NO deben gatillar — son preguntas cosméticas legítimas.
        safe = [
            "¿Qué productos tienes?",
            "¿Cuánto cuesta el jabón de coco?",
            "¿Qué ingredientes tiene?",
            "¿Es para piel grasa o seca?",
            "¿Cómo lo aplico?",
            "Gracias por la info",
        ]
        for c in safe:
            self.assertFalse(_detect_medical_query(c), f"falso positivo: {c!r}")

    def test_empty_text(self):
        self.assertFalse(_detect_medical_query(""))
        self.assertFalse(_detect_medical_query(None))  # type: ignore


class DrugPurchaseDetectorTests(unittest.TestCase):
    """Solicitudes de compra de medicamentos — Meta Commerce Policy."""

    def test_specific_drug_names(self):
        cases = [
            "¿Vendes ibuprofeno?",
            "Necesito paracetamol",
            "¿Tienes amoxicilina?",
            "Quiero comprar antibiótico",
            "Vendes loratadina",
            "Necesito viagra",
        ]
        for c in cases:
            self.assertTrue(_detect_drug_purchase_request(c), f"falló: {c!r}")

    def test_generic_med_terms(self):
        cases = [
            "¿Venden medicamentos?",
            "Necesito una pastilla para el dolor",
            "Vendes medicamento para la fiebre",
        ]
        for c in cases:
            self.assertTrue(_detect_drug_purchase_request(c), f"falló: {c!r}")

    def test_safe_questions_pass_through(self):
        safe = [
            "¿Qué productos tienes?",
            "¿Cuánto cuesta el jabón?",
            "¿Cómo se usa?",
            "¿Hacen envíos?",
            "Quiero comprar 2 jabones",
        ]
        for c in safe:
            self.assertFalse(_detect_drug_purchase_request(c), f"falso positivo: {c!r}")

    def test_empty_text(self):
        self.assertFalse(_detect_drug_purchase_request(""))
        self.assertFalse(_detect_drug_purchase_request(None))  # type: ignore


class CrossDomainTests(unittest.TestCase):
    """Validar que ambos detectores son vertical-agnósticos.
    Funcionan igual sin importar el dominio del tenant (cosmética, tech,
    comida, fashion, etc.)."""

    def test_medical_query_works_for_tech_product(self):
        # Cliente de un tenant de tecnología pregunta algo médico.
        # El detector debe dispararse igual.
        self.assertTrue(_detect_medical_query(
            "Tengo dermatitis, ¿el láser me cura el problema?"
        ))

    def test_drug_request_works_for_food_product(self):
        # Cliente de un tenant de comida pregunta por medicamento.
        self.assertTrue(_detect_drug_purchase_request(
            "¿Tu suplemento tiene ibuprofeno?"
        ))


if __name__ == "__main__":
    unittest.main()
