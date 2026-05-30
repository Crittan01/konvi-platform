"""Tests del safety/domain_filter (rev. 104, F1-1).

Valida los detectores extraídos del monolito orchestrator.py al módulo
`safety/domain_filter.py`. Cubre Meta Healthcare + Commerce Policy.

Carga el módulo via importlib para no contaminar sys.modules['safety'] entre
tests del proyecto.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOMAIN_PATH = REPO / "services/ai-orchestrator/safety/domain_filter.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_safety_domain_under_test", str(DOMAIN_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DetectMedicalQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = _load()

    def test_disease_names_trigger(self):
        for q in (
            "¿Tu producto cura el acné?",
            "Tengo psoriasis, ¿sirve?",
            "¿Sirve para el cáncer?",
            "Estoy embarazada, ¿puedo usar?",
            "¿Es seguro en lactancia?",
            "Tengo dermatitis severa",
        ):
            self.assertTrue(self.df.detect_medical_query(q),
                            f"esperaba True para {q!r}")

    def test_diagnosis_lang_trigger(self):
        for q in (
            "¿Qué tratamiento me recomiendas?",
            "¿Qué medicamento me darías?",
            "Necesito una receta médica",
            "¿Es bueno para mi alergia?",
        ):
            self.assertTrue(self.df.detect_medical_query(q),
                            f"esperaba True para {q!r}")

    def test_neutral_queries_no_trigger(self):
        for q in (
            "Hola, ¿qué jabones tienen?",
            "Quiero comprar un sérum",
            "¿Cuánto cuesta?",
            "¿A qué ciudad envían?",
        ):
            self.assertFalse(self.df.detect_medical_query(q),
                             f"esperaba False para {q!r}")

    def test_empty_or_none(self):
        self.assertFalse(self.df.detect_medical_query(""))
        self.assertFalse(self.df.detect_medical_query(None))


class DetectDrugPurchaseRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = _load()

    def test_drug_names_trigger(self):
        for q in (
            "¿Vendes ibuprofeno?",
            "Necesito acetaminofén",
            "Quiero comprar antibiótico",
            "¿Tienen viagra?",
            "Pastilla para el dolor",
        ):
            self.assertTrue(self.df.detect_drug_purchase_request(q),
                            f"esperaba True para {q!r}")

    def test_neutral_no_trigger(self):
        for q in (
            "Hola, ¿qué productos tienen?",
            "Quiero un sérum facial",
            "¿Cuánto cuesta el envío?",
        ):
            self.assertFalse(self.df.detect_drug_purchase_request(q),
                             f"esperaba False para {q!r}")

    def test_empty_or_none(self):
        self.assertFalse(self.df.detect_drug_purchase_request(""))
        self.assertFalse(self.df.detect_drug_purchase_request(None))


class PhraseConstantsAreSensibleTests(unittest.TestCase):
    """Smoke check sobre las constantes — defensa contra regresión accidental."""

    @classmethod
    def setUpClass(cls):
        cls.df = _load()

    def test_medical_phrases_non_empty(self):
        self.assertGreater(len(self.df.MEDICAL_QUERY_PHRASES), 20)

    def test_drug_phrases_non_empty(self):
        self.assertGreater(len(self.df.DRUG_PURCHASE_PHRASES), 15)

    def test_phrases_are_lowercase(self):
        # El detector compara contra texto normalizado lowercase. Las
        # frases en las constantes deben estar lowercase para que el
        # `phrase in normalized` funcione.
        for p in self.df.MEDICAL_QUERY_PHRASES:
            self.assertEqual(p, p.lower(), f"phrase no lowercase: {p!r}")
        for p in self.df.DRUG_PURCHASE_PHRASES:
            self.assertEqual(p, p.lower(), f"phrase no lowercase: {p!r}")


if __name__ == "__main__":
    unittest.main()
