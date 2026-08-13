"""Rev. 97 — Tests del detector + handler de Habeas Data Art. 14 vía WhatsApp.

Cobertura:
  • _detect_data_export_intent: positivos por token, negativos.
  • Exclusión de revocaciones (no debe disparar export para "elimina mis datos").
  • _build_customer_data_summary: shape del texto, masking PII,
    contact no encontrado, error gracioso.
  • _mask_value: mascarado parcial.

Tests aislados con mocks (sin Supabase real).
"""
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from orchestrator import (  # noqa: E402
    _detect_data_export_intent,
    _build_customer_data_summary,
    _mask_value,
)


class DetectDataExportIntentTests(unittest.TestCase):

    def test_envia_mis_datos(self):
        self.assertTrue(_detect_data_export_intent("envíame mis datos"))
        self.assertTrue(_detect_data_export_intent("Envia mis datos por favor"))

    def test_que_tienen_sobre_mi(self):
        self.assertTrue(_detect_data_export_intent("¿Qué tienen sobre mí?"))
        self.assertTrue(_detect_data_export_intent("qué información tienen sobre mí"))
        self.assertTrue(_detect_data_export_intent("que datos guardan sobre mi"))

    def test_habeas_data_formal(self):
        self.assertTrue(_detect_data_export_intent("Quiero ejercer Habeas Data"))
        self.assertTrue(_detect_data_export_intent("solicito mis datos personales"))

    def test_portabilidad(self):
        self.assertTrue(_detect_data_export_intent(
            "Pido portabilidad de datos por favor"
        ))
        self.assertTrue(_detect_data_export_intent("exportar mis datos"))

    def test_negative_chitchat(self):
        self.assertFalse(_detect_data_export_intent("Hola buenos días"))
        self.assertFalse(_detect_data_export_intent("¿Cuánto cuesta el aceite?"))
        self.assertFalse(_detect_data_export_intent(""))

    def test_revocation_does_not_trigger_export(self):
        # "elimina mis datos" es revocation, no export. Detector export
        # debe excluir tokens de revocación.
        self.assertFalse(_detect_data_export_intent("elimina mis datos"))
        self.assertFalse(_detect_data_export_intent("borra mis datos"))
        self.assertFalse(_detect_data_export_intent("revoco el consentimiento"))

    def test_handles_accents_and_case(self):
        self.assertTrue(_detect_data_export_intent("ENVÍAME MIS DATOS"))
        self.assertTrue(_detect_data_export_intent("Que información tienen sobre mí"))


class MaskValueTests(unittest.TestCase):

    def test_masks_long_value(self):
        # "12345678901" → "12*****8901"
        result = _mask_value("12345678901")
        self.assertTrue(result.startswith("12"))
        self.assertTrue(result.endswith("8901"))
        self.assertIn("*", result)

    def test_short_value_fully_masked(self):
        self.assertEqual(_mask_value("123"), "***")
        self.assertEqual(_mask_value("abcde"), "*****")

    def test_empty_returns_placeholder(self):
        self.assertEqual(_mask_value(None), "(no registrado)")
        self.assertEqual(_mask_value(""), "(no registrado)")


class BuildCustomerDataSummaryTests(unittest.TestCase):

    def setUp(self):
        self.sb = MagicMock()
        # Setup contact found.
        contact_chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        contact_chain.execute.return_value = MagicMock(data=[{
            "name": "Cristian Maldonado",
            "email": "test@example.com",
            "phone": "+573125835649",
            "document_type": "CC",
            "document_number": "1234567890",
            "address": {"street": "Calle 1"},
            "consent_given": True,
            "consent_given_at": "2026-04-01",
            "consent_revoked_at": None,
        }])
        # Orders count.
        orders_count_chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        orders_count_chain.execute.return_value = MagicMock(count=3)

    def test_summary_includes_all_pii_sections(self):
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        self.assertIn("Nombre", text)
        self.assertIn("Email", text)
        self.assertIn("Teléfono", text)
        self.assertIn("Documento", text)
        self.assertIn("Dirección", text)
        self.assertIn("Consentimiento", text)
        self.assertIn("Pedidos asociados", text)

    def test_consent_active_shows_check(self):
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        self.assertIn("Activo", text)

    def test_phone_is_masked_not_plaintext(self):
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        # No debe aparecer el phone completo.
        self.assertNotIn("+573125835649", text)
        # Pero sí los últimos 4.
        self.assertIn("5649", text)

    def test_document_number_is_masked(self):
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        self.assertNotIn("1234567890", text)
        self.assertIn("7890", text)

    def test_includes_legal_reference(self):
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        self.assertIn("Habeas Data", text)
        self.assertIn("1581", text)

    def test_revoked_consent_shows_lock(self):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[{
            "name": None, "email": None, "phone": "+57x",
            "document_type": None, "document_number": None,
            "address": None,
            "consent_given": False,
            "consent_revoked_at": "2026-05-01",
        }])
        text = _build_customer_data_summary(self.sb, "c-1", "t-1")
        self.assertIn("Revocado", text)


class BuildSummaryNotFoundTests(unittest.TestCase):

    def test_contact_not_found_graceful_message(self):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[])
        text = _build_customer_data_summary(sb, "missing", "t-1")
        self.assertIn("No tenemos registros", text)


class BuildSummaryErrorHandlingTests(unittest.TestCase):

    def test_db_error_returns_fallback_message(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("DB down")
        text = _build_customer_data_summary(sb, "c-1", "t-1")
        # Mensaje fallback no debe leak el error.
        self.assertNotIn("DB down", text)
        self.assertIn("24-48h", text)
        self.assertIn("1581", text)


if __name__ == "__main__":
    unittest.main()
