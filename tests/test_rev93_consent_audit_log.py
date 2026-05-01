"""Rev. 93 — Tests del audit log inmutable de consent (Art. 9).

Cobertura:
  • _hash_phone: hash sha256 estable del phone para lookup post-anonymization.
  • _log_consent_event: insert en consent_audit_log con shape correcto.
  • _log_pii_access: insert en pii_access_log con shape correcto.
  • _record_consent: ahora también escribe consent_audit_log.

Las migraciones reales (consent_audit_log + pii_access_log) son SQL
y se prueban en tests E2E con DB real. Estos tests validan que el
código Python invoca las tablas correctamente.
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _hash_phone,
    _log_consent_event,
    _log_pii_access,
    _record_consent,
)


class HashPhoneTests(unittest.TestCase):

    def test_hash_is_deterministic(self):
        h1 = _hash_phone("+573125835649")
        h2 = _hash_phone("+573125835649")
        self.assertEqual(h1, h2)

    def test_hash_strips_format(self):
        # Diferentes formatos del mismo phone → mismo hash.
        h1 = _hash_phone("+573125835649")
        h2 = _hash_phone("573125835649")
        h3 = _hash_phone("+57 312 583 5649")
        h4 = _hash_phone("+57-312-583-5649")
        self.assertEqual(h1, h2)
        self.assertEqual(h2, h3)
        self.assertEqual(h3, h4)

    def test_hash_is_sha256_length(self):
        h = _hash_phone("+573125835649")
        self.assertEqual(len(h), 64)  # sha256 hex = 64 chars

    def test_hash_none_returns_none(self):
        self.assertIsNone(_hash_phone(None))
        self.assertIsNone(_hash_phone(""))


class LogConsentEventTests(unittest.TestCase):

    def setUp(self):
        self.supabase = MagicMock()
        self.insert_chain = self.supabase.table.return_value.insert
        self.insert_chain.return_value.execute.return_value = MagicMock()

    def _captured_row(self):
        if not self.insert_chain.call_args:
            return {}
        args, _kwargs = self.insert_chain.call_args
        return args[0] if args else {}

    def test_insert_to_correct_table(self):
        _log_consent_event(
            self.supabase,
            tenant_id="t-1", contact_id="c-1",
            phone="+573125835649", event="granted",
        )
        self.supabase.table.assert_any_call("consent_audit_log")

    def test_row_shape_includes_required_fields(self):
        _log_consent_event(
            self.supabase,
            tenant_id="t-1", contact_id="c-1",
            phone="+573125835649", event="revoked",
            source="whatsapp", conversation_id="conv-1",
            evidence={"reason": "test"},
        )
        row = self._captured_row()
        self.assertEqual(row["tenant_id"], "t-1")
        self.assertEqual(row["contact_id"], "c-1")
        self.assertEqual(row["event"], "revoked")
        self.assertEqual(row["source"], "whatsapp")
        self.assertEqual(row["conversation_id"], "conv-1")
        self.assertEqual(row["evidence"], {"reason": "test"})
        # phone debe estar hasheado, NO en plaintext.
        self.assertNotIn("+573125835649", str(row))
        self.assertEqual(len(row["phone_hash"]), 64)

    def test_log_failure_does_not_raise(self):
        # Si insert falla, _log_consent_event no debe propagar excepción.
        self.insert_chain.return_value.execute.side_effect = Exception("DB down")
        # No debe levantar.
        _log_consent_event(
            self.supabase, tenant_id="t-1", contact_id="c-1",
            phone="x", event="granted",
        )


class LogPiiAccessTests(unittest.TestCase):

    def setUp(self):
        self.supabase = MagicMock()
        self.insert_chain = self.supabase.table.return_value.insert
        self.insert_chain.return_value.execute.return_value = MagicMock()

    def _captured_row(self):
        args, _ = self.insert_chain.call_args
        return args[0]

    def test_insert_to_correct_table(self):
        _log_pii_access(
            self.supabase,
            tenant_id="t-1", contact_id="c-1",
            accessed_by="user:alice@kaiu.co",
            purpose="inbox_view",
            fields_accessed=["name", "email"],
        )
        self.supabase.table.assert_any_call("pii_access_log")

    def test_row_shape_includes_fields_accessed(self):
        _log_pii_access(
            self.supabase,
            tenant_id="t-1", contact_id="c-1",
            accessed_by="agent:orchestrator",
            purpose="wompi_checkout",
            fields_accessed=["document_number", "name", "email", "phone"],
        )
        row = self._captured_row()
        self.assertEqual(row["accessed_by"], "agent:orchestrator")
        self.assertEqual(row["purpose"], "wompi_checkout")
        self.assertIn("document_number", row["fields_accessed"])

    def test_log_failure_silent(self):
        self.insert_chain.return_value.execute.side_effect = Exception("X")
        # No debe levantar.
        _log_pii_access(
            self.supabase, tenant_id="t", contact_id="c",
            accessed_by="x", purpose="x", fields_accessed=[],
        )


class RecordConsentWritesAuditTests(unittest.TestCase):
    """`_record_consent` (rev. 93) debe escribir tanto a `contacts`
    como a `consent_audit_log`."""

    def setUp(self):
        self.supabase = MagicMock()
        # Setup chained mocks que cubre ambas operaciones.
        # SELECT: para fetch del phone existing.
        select_chain = self.supabase.table.return_value.select.return_value
        select_chain.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"phone": "+573125835649"}]
        )
        # UPDATE en contacts.
        update_chain = self.supabase.table.return_value.update.return_value
        update_chain.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        # INSERT en consent_audit_log.
        self.supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

    def test_grant_writes_audit_event_granted(self):
        _record_consent(self.supabase, "c-1", "t-1",
                        given=True, conversation_id="conv-1")
        # Buscar la llamada insert en consent_audit_log.
        calls = self.supabase.table.call_args_list
        tables_called = [c.args[0] for c in calls if c.args]
        self.assertIn("consent_audit_log", tables_called)

    def test_revoke_writes_audit_event_revoked(self):
        _record_consent(self.supabase, "c-1", "t-1",
                        given=False, conversation_id="conv-1")
        calls = self.supabase.table.call_args_list
        tables_called = [c.args[0] for c in calls if c.args]
        self.assertIn("consent_audit_log", tables_called)
        self.assertIn("contacts", tables_called)


if __name__ == "__main__":
    unittest.main()
