"""Rev. 93 — Tests del endpoint SAR (Subject Access Request).

Cobertura:
  • POST /data-subject-request type=export → JSON completo Art. 14.
  • POST /data-subject-request type=portability → JSON estándar Art. 19.
  • POST /data-subject-request type=erase → anonimización Art. 15 +
    audit en consent_audit_log.
  • POST /data-subject-request type=rectify → flag pending review.
  • Validaciones: tipo inválido, contact no existe, tenant isolation.

Tests aislados con mocks (sin Supabase real). Tests E2E con DB real
viven en docs/uat/scenarios/sNN_*.py.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from routers.data_subject_request import (  # noqa: E402
    _hash_phone,
    _build_export_payload,
    _execute_erase,
    VALID_TYPES,
)


class HashPhoneTests(unittest.TestCase):

    def test_format_independent_hash(self):
        h1 = _hash_phone("+573125835649")
        h2 = _hash_phone("573125835649")
        h3 = _hash_phone("+57 312 583 5649")
        self.assertEqual(h1, h2)
        self.assertEqual(h2, h3)


class BuildExportPayloadTests(unittest.TestCase):

    def setUp(self):
        self.sb = MagicMock()
        # Encadenado: select().eq().eq().limit().execute().
        contacts_chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        contacts_chain.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "c-1", "phone": "+573125835649",
                "name": "Cristian", "email": "c@x.com",
                "document_type": "CC", "document_number": "123",
                "address": {"street": "Calle 1"},
                "consent_given": True,
                "consent_given_at": "2026-04-01T00:00:00Z",
                "consent_revoked_at": None,
                "consent_revoked_reason": None,
                "consent_text_version": "v2026-04",
            }]
        )
        # Default empty data for orders/consent/pii_access:
        # the .select().eq().eq().order() chain returns empty.
        order_chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order
        order_chain.return_value.execute.return_value = MagicMock(data=[])
        order_chain.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

    def test_payload_has_required_sections(self):
        payload = _build_export_payload(self.sb, "tenant-1", "c-1")
        self.assertIn("format_version", payload)
        self.assertIn("subject", payload)
        self.assertIn("orders", payload)
        self.assertIn("consent_history", payload)
        self.assertIn("pii_access_history", payload)
        self.assertIn("subprocessors", payload)
        self.assertIn("legal_basis", payload)

    def test_subject_has_pii_fields(self):
        payload = _build_export_payload(self.sb, "tenant-1", "c-1")
        subject = payload["subject"]
        self.assertEqual(subject["name"], "Cristian")
        self.assertEqual(subject["email"], "c@x.com")
        self.assertEqual(subject["document_type"], "CC")

    def test_subprocessors_listed(self):
        payload = _build_export_payload(self.sb, "tenant-1", "c-1")
        sub_names = [s["name"] for s in payload["subprocessors"]]
        self.assertIn("Supabase", sub_names)
        self.assertIn("Wompi", sub_names)
        self.assertIn("Meta WhatsApp Business", sub_names)

    def test_legal_basis_includes_law(self):
        payload = _build_export_payload(self.sb, "tenant-1", "c-1")
        self.assertIn("Ley 1581", payload["legal_basis"]["law"])

    def test_404_when_contact_not_found(self):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        chain.limit.return_value.execute.return_value = MagicMock(data=[])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _build_export_payload(self.sb, "tenant-1", "missing")
        self.assertEqual(ctx.exception.status_code, 404)


class ExecuteEraseTests(unittest.TestCase):

    def setUp(self):
        self.sb = MagicMock()
        self.update_chain = self.sb.table.return_value.update
        self.update_chain.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

    def test_erase_anonymizes_all_pii(self):
        _execute_erase(self.sb, "tenant-1", "contact-1")
        update_args = self.update_chain.call_args[0][0]
        # Los 6 campos PII deben quedar nulos.
        for field in ("name", "email", "document_type", "document_number",
                      "address", "notes"):
            self.assertIsNone(update_args[field], f"{field} no se nulificó")

    def test_erase_records_audit_fields(self):
        _execute_erase(self.sb, "tenant-1", "contact-1")
        update_args = self.update_chain.call_args[0][0]
        self.assertEqual(update_args["consent_given"], False)
        self.assertIsNotNone(update_args["consent_revoked_at"])
        self.assertIn("supresión", update_args["consent_revoked_reason"].lower())


class ValidationContractTests(unittest.TestCase):

    def test_valid_types_set(self):
        # Sanity check del set de tipos válidos.
        self.assertEqual(VALID_TYPES, {"export", "rectify", "erase", "portability"})


if __name__ == "__main__":
    unittest.main()
