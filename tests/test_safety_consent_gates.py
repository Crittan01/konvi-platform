"""Tests del safety/consent_gates (rev. 104, F1-1 batch 4)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "services/ai-orchestrator/safety/consent_gates.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_safety_consent_under_test", str(PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RevocationIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_explicit_revocation_trigger(self):
        for q in (
            "Elimina mis datos por favor",
            "borrar todos mis datos",
            "Quiero ser eliminado",
            "Revoco el consentimiento",
            "olvida mis datos",
            "no guardes mis datos",
        ):
            self.assertTrue(self.mod.detect_revocation_intent(q),
                            f"esperaba True para {q!r}")

    def test_neutral_no_trigger(self):
        for q in (
            "Hola, ¿qué tienen?",
            "Quiero comprar",
            "Mis datos son los mismos",
        ):
            self.assertFalse(self.mod.detect_revocation_intent(q))


class DataExportIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_export_phrases_trigger(self):
        for q in (
            "envíame mis datos",
            "Quiero mis datos",
            "Habeas data por favor",
            "qué datos tienen sobre mí",
            "Exportar mis datos",
        ):
            self.assertTrue(self.mod.detect_data_export_intent(q),
                            f"esperaba True para {q!r}")

    def test_revocation_blocks_export(self):
        # Si hay revocation token, export NO dispara (revocation gana).
        self.assertFalse(self.mod.detect_data_export_intent(
            "Elimina mis datos y mándame mis datos"
        ))

    def test_rectification_blocks_export(self):
        # Si hay rectification token, export NO dispara.
        self.assertFalse(self.mod.detect_data_export_intent(
            "actualiza mi email y dame mis datos"
        ))


class RectificationIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_rect_phrases_trigger(self):
        for q in (
            "Quiero actualizar mi email",
            "Corrige mis datos",
            "modificar mis datos",
            "tienen mal mis datos",
        ):
            self.assertTrue(self.mod.detect_rectification_intent(q),
                            f"esperaba True para {q!r}")

    def test_revocation_blocks_rect(self):
        self.assertFalse(self.mod.detect_rectification_intent(
            "Elimina mis datos y actualiza mi email"
        ))


class MinorIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_explicit_minor_trigger(self):
        for q in (
            "Soy menor de edad",
            "soy menor de 18",
            "Estoy en bachillerato",
            "tengo permiso de mis padres",
        ):
            self.assertTrue(self.mod.detect_minor_intent(q),
                            f"esperaba True para {q!r}")

    def test_age_under_18_trigger(self):
        for q in (
            "Tengo 16 años",
            "tengo 17 años de edad",
            "tengo 10 anitos",
        ):
            self.assertTrue(self.mod.detect_minor_intent(q),
                            f"esperaba True para {q!r}")

    def test_age_over_18_no_trigger(self):
        for q in (
            "Tengo 25 años",
            "tengo 30 anos",
        ):
            self.assertFalse(self.mod.detect_minor_intent(q),
                             f"esperaba False para {q!r}")

    def test_neutral_no_trigger(self):
        for q in (
            "Hola, ¿qué jabones?",
            "Quiero comprar",
            "tengo 16 productos en mi lista",  # falso negativo OK — lista, no edad
        ):
            self.assertFalse(self.mod.detect_minor_intent(q))


if __name__ == "__main__":
    unittest.main()
