"""Tests del invariant `assert_cordial_connector_for_direct_question` (rev. 104).

Operacionaliza la regla del prompt `_HUMAN_STYLE_GUIDE`:
> "Si el primer mensaje del cliente es una PREGUNTA DIRECTA (sin saludo),
> abre con un conector cordial (Claro, Por supuesto, Te cuento, Con gusto,
> Listo) + va al grano."

Caso runtime motivador (S03[new] 2026-05-04):
  Cliente: "¿Cuál es la política de devoluciones?"
  Bot:     "Aceptamos devoluciones dentro de los..."
  → Falta conector cordial. Rewrite: "Claro, aceptamos devoluciones..."
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_invariants():
    path = REPO / "services/ai-orchestrator/outbound/invariants.py"
    spec = importlib.util.spec_from_file_location(
        "_inv_cc_test", str(path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class CordialConnectorInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _load_invariants()

    def test_fires_when_question_word_at_start(self):
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Aceptamos devoluciones dentro de los 15 días.",
            history=[{"direction": "inbound", "content": "Cuál es la política de devoluciones?"}],
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(any(rewrite.startswith(c) for c in ("Mira, aceptamos", "Te cuento, aceptamos", "Verás, aceptamos")))

    def test_neutral_connector_works_for_denial_response(self):
        # Caso runtime: bot deniega — el conector debe ser neutro (NO "Claro").
        result = self.inv.assert_cordial_connector_for_direct_question(
            "No comercializamos medicamentos. Para eso tu droguería.",
            history=[{"direction": "inbound", "content": "Vendes ibuprofeno?"}],
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertFalse(rewrite.lower().startswith("claro,"))
        self.assertTrue(any(
            rewrite.startswith(c)
            for c in ("Mira, no", "Te cuento, no", "Verás, no")
        ))

    def test_fires_when_question_mark_at_end(self):
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Te ayudo con eso.",
            history=[{"direction": "inbound", "content": "Tienen envío gratis?"}],
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(any(
            rewrite.startswith(c)
            for c in ("Mira, te ayudo", "Te cuento, te ayudo", "Verás, te ayudo")
        ))

    def test_skips_when_client_greeted(self):
        # "Hola, cuál es..." → tiene saludo, no es pregunta directa pura.
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Aceptamos devoluciones dentro de los 15 días.",
            history=[{"direction": "inbound", "content": "Hola, cuál es la política?"}],
        )
        self.assertIsNone(result)

    def test_skips_when_bot_opens_with_connector(self):
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Listo, aceptamos devoluciones dentro de los 15 días.",
            history=[{"direction": "inbound", "content": "Cuál es la política?"}],
        )
        self.assertIsNone(result)

    def test_skips_when_bot_opens_with_greeting(self):
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Buenas tardes! Aceptamos devoluciones...",
            history=[{"direction": "inbound", "content": "Cuál es la política?"}],
        )
        self.assertIsNone(result)

    def test_skips_when_not_first_outbound(self):
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Aceptamos devoluciones...",
            history=[
                {"direction": "inbound", "content": "Cuál es la política?"},
                {"direction": "outbound", "content": "Te cuento..."},
                {"direction": "inbound", "content": "Otra cosa"},
            ],
        )
        self.assertIsNone(result)

    def test_skips_when_inbound_is_not_a_question(self):
        # Cliente afirma algo, no pregunta. Invariant no aplica.
        result = self.inv.assert_cordial_connector_for_direct_question(
            "Te confirmo que sí tenemos.",
            history=[{"direction": "inbound", "content": "Quiero comprar un jabón"}],
        )
        self.assertIsNone(result)

    def test_preserves_full_content(self):
        # El rewrite debe preservar todo el contenido tras la primera letra.
        original = "Despachamos en 1 día hábil para Bogotá.\n\nMás detalles en KB."
        result = self.inv.assert_cordial_connector_for_direct_question(
            original,
            history=[{"direction": "inbound", "content": "Cuándo despachan?"}],
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(any(
            rewrite.startswith(c) for c in ("Mira, ", "Te cuento, ", "Verás, ")
        ))
        self.assertIn("despachamos en 1 día hábil", rewrite)
        self.assertIn("Más detalles en KB", rewrite)


if __name__ == "__main__":
    unittest.main()
