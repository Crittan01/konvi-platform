"""Rev. 89.b — Test de regresión: loop infinito de consent.

Bug observado en log conv f27516bb (2026-04-30 21:16-21:21):
  Bot pregunta: "¿Estás de acuerdo?"
  Cliente: "Sí"
  Bot REPITE: "¿Estás de acuerdo?"   ← LOOP

Causa: _CONSENT_QUESTION_MARKERS solo tenía "autorizas". El nuevo
prompt UX-cordial rev. 89 termina en "¿Estás de acuerdo?". Los
detectores no reconocían el outbound como pregunta de consent.

Fix: agregar markers del nuevo prompt cordial.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _last_outbound_was_consent_question,
    _CONSENT_QUESTION_MARKERS,
    CONSENT_QUESTION_TEMPLATE,
)


class ConsentMarkersCoverNewWordingTests(unittest.TestCase):

    def test_new_template_is_recognized(self):
        """El nuevo prompt UX-cordial debe ser detectado como consent question."""
        outbound = {"direction": "outbound", "content": CONSENT_QUESTION_TEMPLATE}
        history = [outbound]
        self.assertTrue(_last_outbound_was_consent_question(history))

    def test_estas_de_acuerdo_alone_recognized(self):
        outbound = {
            "direction": "outbound",
            "content": "¡Voy a continuar! ¿Estás de acuerdo?",
        }
        self.assertTrue(_last_outbound_was_consent_question([outbound]))

    def test_legacy_autorizas_still_recognized(self):
        """Versiones previas del prompt seguían diciendo "Me autorizas?"."""
        outbound = {
            "direction": "outbound",
            "content": "Voy a guardar tus datos. ¿Me autorizas?",
        }
        self.assertTrue(_last_outbound_was_consent_question([outbound]))

    def test_no_consent_marker_returns_false(self):
        outbound = {
            "direction": "outbound",
            "content": "¿Cuál es tu correo electrónico?",
        }
        self.assertFalse(_last_outbound_was_consent_question([outbound]))

    def test_empty_history(self):
        self.assertFalse(_last_outbound_was_consent_question([]))


class MarkersCompleteTests(unittest.TestCase):
    """Sanity: la lista contiene markers para todas las versiones del prompt."""

    def test_estas_de_acuerdo_in_markers(self):
        # Sin acento Y con acento (normalización podría quitar acentos)
        markers_lower = [m.lower() for m in _CONSENT_QUESTION_MARKERS]
        self.assertTrue(
            any("estas de acuerdo" in m or "está de acuerdo" in m or "estás de acuerdo" in m
                for m in markers_lower)
        )

    def test_autorizas_in_markers(self):
        # Legacy support
        self.assertIn("autorizas", _CONSENT_QUESTION_MARKERS)


if __name__ == "__main__":
    unittest.main()
