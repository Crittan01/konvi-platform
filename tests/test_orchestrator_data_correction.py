"""
Tests GAP-1: Corrección de datos en READY_FOR_SUMMARY.

Cubre:
- _detect_correction_intent: detecta email, nombre, dirección
- _detect_correction_intent: no detecta sin señal de corrección
- _detect_correction_intent: no detecta afirmaciones normales
- _clear_contact_field: llama update con el campo correcto
- Variantes de frases reales de clientes
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _detect_correction_intent, _clear_contact_field, _CORRECTION_PROMPT


class DetectCorrectionIntentTests(unittest.TestCase):

    # ── Email ──────────────────────────────────────────────────────────────────

    def test_email_mal(self):
        self.assertEqual(_detect_correction_intent("el email está mal"), "email")

    def test_correo_incorrecto(self):
        self.assertEqual(_detect_correction_intent("el correo está incorrecto"), "email")

    def test_cambiar_email(self):
        self.assertEqual(_detect_correction_intent("quiero cambiar el email"), "email")

    def test_correo_equivocado(self):
        self.assertEqual(_detect_correction_intent("puse el correo equivocado"), "email")

    # ── Nombre ────────────────────────────────────────────────────────────────

    def test_nombre_mal(self):
        self.assertEqual(_detect_correction_intent("el nombre está mal"), "name")

    def test_cambiar_nombre(self):
        self.assertEqual(_detect_correction_intent("quiero cambiar mi nombre"), "name")

    def test_apellido_incorrecto(self):
        self.assertEqual(_detect_correction_intent("mi apellido está incorrecto"), "name")

    # ── Dirección ─────────────────────────────────────────────────────────────

    def test_direccion_mal(self):
        self.assertEqual(_detect_correction_intent("la dirección está mal"), "address")

    def test_domicilio_incorrecto(self):
        self.assertEqual(_detect_correction_intent("el domicilio está incorrecto"), "address")

    def test_cambiar_direccion(self):
        self.assertEqual(_detect_correction_intent("quiero cambiar la dirección"), "address")

    def test_calle_equivocada(self):
        self.assertEqual(_detect_correction_intent("la calle está equivocada"), "address")

    # ── Sin corrección ────────────────────────────────────────────────────────

    def test_confirmacion_positiva(self):
        self.assertIsNone(_detect_correction_intent("sí, todo está correcto"))

    def test_afirmacion_simple(self):
        self.assertIsNone(_detect_correction_intent("confirmo"))

    def test_mensaje_compra(self):
        self.assertIsNone(_detect_correction_intent("quiero comprar 2 unidades"))

    def test_saludo(self):
        self.assertIsNone(_detect_correction_intent("hola buenas tardes"))

    def test_texto_vacio(self):
        self.assertIsNone(_detect_correction_intent(""))

    def test_negacion_sin_campo(self):
        # "está mal" sin campo específico → None (no sabe qué corregir)
        self.assertIsNone(_detect_correction_intent("está mal"))

    def test_query_carrier(self):
        self.assertIsNone(_detect_correction_intent("¿cuánto tarda la opción económica?"))


class ClearContactFieldTests(unittest.TestCase):

    def _mock_supabase(self):
        sb = MagicMock()
        sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        return sb

    def test_clears_email(self):
        sb = self._mock_supabase()
        _clear_contact_field(sb, "contact-1", "tenant-1", "email")
        sb.table.return_value.update.assert_called_once_with({"email": None})

    def test_clears_name(self):
        sb = self._mock_supabase()
        _clear_contact_field(sb, "contact-1", "tenant-1", "name")
        sb.table.return_value.update.assert_called_once_with({"name": None})

    def test_clears_address(self):
        sb = self._mock_supabase()
        _clear_contact_field(sb, "contact-1", "tenant-1", "address")
        sb.table.return_value.update.assert_called_once_with({"address": None})


class CorrectionPromptsTests(unittest.TestCase):

    def test_all_fields_have_prompt(self):
        for field in ("email", "name", "address"):
            self.assertIn(field, _CORRECTION_PROMPT)
            self.assertTrue(len(_CORRECTION_PROMPT[field]) > 10)

    def test_prompts_are_friendly(self):
        for field, prompt in _CORRECTION_PROMPT.items():
            self.assertIn("Entendido", prompt, f"Prompt for {field} should be friendly")


if __name__ == "__main__":
    unittest.main()
