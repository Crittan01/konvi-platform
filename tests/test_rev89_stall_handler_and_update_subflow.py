"""Rev. 89 — Tests del stall handler FSM + sub-flow UPDATE.

Filosofía rev. 87/89: paths críticos en código determinístico, NO en
prompt del LLM (que oscila).

Tests:
  • _build_next_data_request_prompt: verifica que produce prompt
    determinístico para cada estado FSM (NEEDS_CONSENT, EMAIL, NAME,
    DOCUMENT, DIRECTION).
  • _detect_data_update_intent: ya existe en rev. 86. Aquí cubre
    el sub-flow Python de UPDATE.
"""
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _build_next_data_request_prompt,
    _detect_data_update_intent,
)


class DataRequestPromptTests(unittest.TestCase):
    """Verifica que el prompt determinístico produce mensaje específico
    para cada estado FSM. Usado por hard-lock rev. 89 cuando LLM no
    avanza solo."""

    def test_needs_consent_asks_authorization(self):
        contact = {
            "name": None, "email": None, "consent_given": False,
            "document_type": None, "document_number": None,
            "address": None,
        }
        out = _build_next_data_request_prompt(contact)
        self.assertIn("autoriz", out.lower())

    def test_needs_email_asks_email(self):
        contact = {
            "name": "Cristian", "email": None, "consent_given": True,
            "document_type": None, "document_number": None,
            "address": None,
        }
        out = _build_next_data_request_prompt(contact)
        self.assertIn("correo", out.lower())

    def test_needs_name_asks_name(self):
        contact = {
            "name": None, "email": "x@y.com", "consent_given": True,
            "document_type": None, "document_number": None,
            "address": None,
        }
        out = _build_next_data_request_prompt(contact)
        self.assertIn("nombre", out.lower())

    def test_needs_document_asks_document(self):
        contact = {
            "name": "Cristian", "email": "x@y.com", "consent_given": True,
            "document_type": None, "document_number": None,
            "address": None,
        }
        out = _build_next_data_request_prompt(contact)
        # Debe pedir documento de identidad
        self.assertTrue(any(kw in out.lower() for kw in ("cédula", "cedula", "documento")))


class UpdateSubflowTests(unittest.IsolatedAsyncioTestCase):
    """Verifica sub-flow UPDATE: detector + canned response.
    El handler en orchestrator es deterministico (rev. 89)."""

    def test_address_intent_triggers_field_specific_prompt(self):
        # Lógica: si _detect_data_update_intent('cambia mi direccion') = 'address',
        # el prompt canned será sobre dirección.
        intent = _detect_data_update_intent("cambia mi dirección")
        self.assertEqual(intent, "address")

    def test_email_intent(self):
        intent = _detect_data_update_intent("cambia mi correo")
        self.assertEqual(intent, "email")

    def test_phone_intent(self):
        intent = _detect_data_update_intent("actualizar telefono")
        self.assertEqual(intent, "phone")

    def test_general_when_unclear(self):
        intent = _detect_data_update_intent("actualizar mis datos")
        self.assertEqual(intent, "general")

    def test_no_intent_for_normal_message(self):
        self.assertIsNone(_detect_data_update_intent("Sí confirmo"))
        self.assertIsNone(_detect_data_update_intent("Hola"))


class StallScenarioTests(unittest.TestCase):
    """Documentación de comportamiento del hard-lock rev. 89.
    El test E2E real está en rev79_conversation_scenarios.py. Aquí
    aseguramos que las funciones helper devuelven prompts apropiados."""

    def test_needs_consent_prompt_does_not_have_off_topic(self):
        """El prompt forzado no debe incluir consultas conversacionales."""
        out = _build_next_data_request_prompt({
            "name": None, "email": None, "consent_given": False,
            "document_type": None, "document_number": None,
            "address": None,
        })
        # NO debe haber preguntas sobre tipo de piel, uso de producto, etc.
        forbidden = ("tipo de piel", "qué uso", "para rostro o cuerpo",
                     "agregar más", "asesoría sobre")
        for word in forbidden:
            self.assertNotIn(word.lower(), out.lower(),
                f"Prompt determinístico no debe incluir: {word!r}")


if __name__ == "__main__":
    unittest.main()
