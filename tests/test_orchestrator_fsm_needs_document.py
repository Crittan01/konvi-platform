"""Tests del estado NEEDS_DOCUMENT en el FSM (rev. 68).

Verifica que el FSM determina correctamente cuándo pedir documento:
- Sin consent → NEEDS_CONSENT (no pasa por document)
- Con consent + name + email + sin doc → NEEDS_DOCUMENT
- Con doc completo + sin direction → NEEDS_DIRECTION
- Con todo → READY_FOR_SUMMARY
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import _determine_transactional_state  # noqa: E402


class FsmNeedsDocumentTests(unittest.TestCase):

    def test_no_contact_returns_consent(self):
        self.assertEqual(_determine_transactional_state({}), "NEEDS_CONSENT")

    def test_no_consent_returns_consent(self):
        self.assertEqual(
            _determine_transactional_state({"consent_given": False, "name": "X", "email": "x@y.com"}),
            "NEEDS_CONSENT",
        )

    def test_consent_no_email_returns_email(self):
        self.assertEqual(
            _determine_transactional_state({"consent_given": True}),
            "NEEDS_EMAIL",
        )

    def test_consent_email_no_name_returns_name(self):
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True, "email": "x@y.com",
            }),
            "NEEDS_NAME",
        )

    def test_consent_email_name_no_document_returns_document(self):
        # Rev. 68: nuevo estado NEEDS_DOCUMENT antes de NEEDS_DIRECTION.
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True,
                "email": "x@y.com",
                "name": "Andrés",
            }),
            "NEEDS_DOCUMENT",
        )

    def test_consent_email_name_partial_document_returns_document(self):
        # Solo type sin number → todavía NEEDS_DOCUMENT.
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True,
                "email": "x@y.com",
                "name": "Andrés",
                "document_type": "CC",
            }),
            "NEEDS_DOCUMENT",
        )
        # Solo number sin type → todavía NEEDS_DOCUMENT.
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True,
                "email": "x@y.com",
                "name": "Andrés",
                "document_number": "1234567890",
            }),
            "NEEDS_DOCUMENT",
        )

    def test_full_document_no_address_returns_direction(self):
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True,
                "email": "x@y.com",
                "name": "Andrés",
                "document_type": "CC",
                "document_number": "1234567890",
            }),
            "NEEDS_DIRECTION",
        )

    def test_full_data_returns_ready(self):
        self.assertEqual(
            _determine_transactional_state({
                "consent_given": True,
                "email": "x@y.com",
                "name": "Andrés",
                "document_type": "CC",
                "document_number": "1234567890",
                "address": {
                    "street": "Calle 1",
                    "city": "Bogotá",
                    "state": "DC",
                    "dane_code": "11001000",
                    "neighborhood": "Chapinero",  # P6 opción C: residencial.
                    "building_type": "casa",
                },
            }),
            "READY_FOR_SUMMARY",
        )


if __name__ == "__main__":
    unittest.main()
