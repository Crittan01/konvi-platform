"""Tests del safety/escalation (rev. 104, F1-1 batch 3)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "services/ai-orchestrator/safety/escalation.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_safety_escalation_under_test", str(PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HumanRequestIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_explicit_phrases_trigger(self):
        # NOTA: la regex legacy NO strip accents, así que las variantes
        # acentuadas como "Comunícame" no matchean — solo las formas
        # exactas en los patrones ("comuniqueme", "hablar con asesor", etc).
        for q in (
            "Quiero hablar con un asesor",
            "Necesito atención humana",
            "Pasame con una persona",      # "pasame" en regex
            "Quiero un agente",
            "Que me llame un humano",
            "Comuniqueme con un vendedor", # forma en regex
            "Contactarme con un asesor",  # 'asesor' está en pattern 3
        ):
            self.assertTrue(self.mod.detect_human_request_intent(q),
                            f"esperaba True para {q!r}")

    def test_neutral_no_trigger(self):
        for q in (
            "Hola, ¿qué tienen?",
            "Tengo una duda",
            "Ayúdame con el envío",
            "Quiero comprar un jabón",
        ):
            self.assertFalse(self.mod.detect_human_request_intent(q),
                             f"esperaba False para {q!r}")

    def test_empty(self):
        self.assertFalse(self.mod.detect_human_request_intent(""))
        self.assertFalse(self.mod.detect_human_request_intent(None))


if __name__ == "__main__":
    unittest.main()
