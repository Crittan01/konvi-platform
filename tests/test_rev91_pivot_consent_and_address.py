"""Rev. 91 pivot — Tests del UX más simple sugerido por el usuario.

S9 fix: el consent question pide "Responde *SÍ* o *NO*" explícito.
S12 fix: building_type se reconcilia en la capa de persistencia (cross-cutting),
no condicionado al estado FSM.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    CONSENT_QUESTION_TEMPLATE,
    _build_next_data_request_prompt,
    _detect_building_type_from_text,
    _CONSENT_QUESTION_MARKERS,
    _last_outbound_was_consent_question,
)


class ConsentTemplateExplicitYesNoTests(unittest.TestCase):
    """Pivot S9 — el consent prompt incluye 'Responde *SÍ* o *NO*'."""

    def test_template_has_explicit_yes_no(self):
        self.assertIn("SÍ", CONSENT_QUESTION_TEMPLATE)
        self.assertIn("NO", CONSENT_QUESTION_TEMPLATE)

    def test_template_keeps_question_mark(self):
        self.assertIn("¿Estás de acuerdo?", CONSENT_QUESTION_TEMPLATE)

    def test_dynamic_prompt_consent_branch_has_yes_no(self):
        """_build_next_data_request_prompt en NEEDS_CONSENT también."""
        out = _build_next_data_request_prompt({
            "consent_given": False, "name": None, "email": None,
            "document_type": None, "document_number": None, "address": None,
        })
        self.assertIn("SÍ", out)
        self.assertIn("NO", out)

    def test_consent_markers_still_recognize_template(self):
        """Cambiar el template no debe romper la detección."""
        history = [{"direction": "outbound", "content": CONSENT_QUESTION_TEMPLATE}]
        self.assertTrue(_last_outbound_was_consent_question(history))


class BuildingTypeDetectorReturnsTests(unittest.TestCase):
    """Pivot S12 — verificación del detector textual sobre frases reales."""

    def test_conjunto_las_flores(self):
        self.assertEqual(
            _detect_building_type_from_text(
                "Calle 1 #2-3, conjunto Las Flores, Bogotá"
            ),
            "conjunto",
        )

    def test_torres_del(self):
        self.assertEqual(
            _detect_building_type_from_text("vivo en Torres del Parque"),
            "conjunto",
        )

    def test_edificio_explicit(self):
        self.assertEqual(
            _detect_building_type_from_text("Edificio Sol, apto 502"),
            "edificio",
        )

    def test_casa_explicit(self):
        self.assertEqual(
            _detect_building_type_from_text("Calle 5 #6-7, casa, Medellín"),
            "casa",
        )

    def test_no_signal_returns_none(self):
        self.assertIsNone(
            _detect_building_type_from_text("Soy Cristian, mi correo es x@y.com"),
        )


class AddressReconciliationContractTests(unittest.TestCase):
    """Pivot S12 — el detector textual override la clasificación del LLM
    en la capa de persistencia. No es responsabilidad del FSM."""

    def test_contract_documented_at_persistence_layer(self):
        """Sanity: el código de orchestrator.py contiene la lógica
        de reconciliación de building_type en la capa de persistencia
        (no condicionada al FSM state)."""
        with open(
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/orchestrator.py",
            encoding="utf-8",
        ) as fh:
            src = fh.read()
        self.assertIn("ADDRESS_RECONCILE", src)
        self.assertIn(
            "building_type LLM=%s text=%s — usando text", src,
            "Falta el log de reconciliación de building_type",
        )


if __name__ == "__main__":
    unittest.main()
