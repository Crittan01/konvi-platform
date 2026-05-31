"""Rev. 92.e — Tests de anonimización completa en revocación de consent.

Cumplimiento Ley 1581/2012 Colombia (Habeas Data):
  • Art. 9: audit de revocación (consent_revoked_at + consent_revoked_reason).
  • Art. 15: derecho de supresión — TODO PII debe anonimizarse al revocar.

Bug pre-rev. 92.e: `_record_consent(given=False)` nullificaba solo
name, email, address, notes. document_type y document_number quedaban
persistidos en DB → exposición regulatoria SIC.

Phone se conserva intencionalmente (canal de comunicación; cliente
puede bloquear si requiere supresión total).
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _record_consent  # noqa: E402


def _capture_update_dict(supabase_mock):
    """Extrae el dict pasado a `update(...)` del mock supabase."""
    update_call = supabase_mock.table.return_value.update
    if not update_call.call_args:
        return {}
    args, _kwargs = update_call.call_args
    return args[0] if args else {}


class RevocationAnonymizationTests(unittest.TestCase):

    def setUp(self):
        self.supabase = MagicMock()
        # Encadenado: table().update().eq().eq().execute()
        chain = self.supabase.table.return_value.update.return_value
        chain.eq.return_value.eq.return_value.execute.return_value = MagicMock()

    def test_revocation_nullifies_all_six_pii_fields(self):
        """Art. 15 — anonimización total de los 6 campos PII de contacts."""
        _record_consent(self.supabase, "contact-id-1", "tenant-1",
                        given=False, conversation_id="conv-1")
        update = _capture_update_dict(self.supabase)
        # Los 6 campos PII deben quedar en None.
        for field in ("name", "email", "document_type", "document_number",
                      "address", "notes"):
            self.assertIn(field, update,
                f"Campo {field!r} faltante en update dict")
            self.assertIsNone(update[field],
                f"Campo {field!r} debería ser None tras revocación, "
                f"pero quedó: {update[field]!r}")

    def test_revocation_keeps_phone_for_channel_continuity(self):
        """Phone NO se nullifica — mantiene canal de WhatsApp."""
        _record_consent(self.supabase, "contact-id-1", "tenant-1",
                        given=False, conversation_id="conv-1")
        update = _capture_update_dict(self.supabase)
        # Phone no debe estar en el update (no se modifica) o si está,
        # NO debe ser None.
        self.assertNotIn("phone", update,
            "phone NO debe modificarse en revocación (canal de comunicación)")

    def test_revocation_records_audit_trail(self):
        """Art. 9 — audit trail obligatorio."""
        _record_consent(self.supabase, "contact-id-1", "tenant-1",
                        given=False, conversation_id="conv-1")
        update = _capture_update_dict(self.supabase)

        self.assertEqual(update.get("consent_given"), False)
        self.assertIsNotNone(update.get("consent_revoked_at"),
            "consent_revoked_at obligatorio (Art. 9 audit)")
        self.assertIn("Revocación", update.get("consent_revoked_reason", ""),
            "consent_revoked_reason obligatorio (Art. 9 audit)")

    def test_consent_grant_does_not_touch_pii(self):
        """`given=True` (otorgar consent) NO debe nullificar PII existente.

        Solo registra metadatos del consent (consent_given, consent_given_at,
        consent_source, etc.) sin tocar los campos PII del contacto.
        """
        _record_consent(self.supabase, "contact-id-1", "tenant-1",
                        given=True, conversation_id="conv-1")
        update = _capture_update_dict(self.supabase)

        # Ningún campo PII debe estar siendo seteado a None.
        for field in ("name", "email", "document_type", "document_number",
                      "address", "notes"):
            self.assertNotIn(field, update,
                f"Otorgar consent NO debe modificar {field!r}")

        # Pero sí debe setear los campos de consent.
        self.assertEqual(update.get("consent_given"), True)
        self.assertIsNotNone(update.get("consent_given_at"))


class HabeasDataComplianceContractTests(unittest.TestCase):
    """Contratos generales del cumplimiento Ley 1581/2012."""

    def test_record_consent_writes_to_contacts_table(self):
        supabase = MagicMock()
        chain = supabase.table.return_value.update.return_value
        chain.eq.return_value.eq.return_value.execute.return_value = MagicMock()

        _record_consent(supabase, "c-1", "t-1", given=False, conversation_id="x")
        # La actualización debe ir a la tabla `contacts`.
        supabase.table.assert_any_call("contacts")

    def test_revocation_filters_by_tenant_and_contact(self):
        """Tenant isolation — no se puede revocar consent cross-tenant."""
        supabase = MagicMock()
        chain = supabase.table.return_value.update.return_value
        eq_chain = chain.eq.return_value
        eq_chain.eq.return_value.execute.return_value = MagicMock()

        _record_consent(supabase, "contact-X", "tenant-Y",
                        given=False, conversation_id="conv")

        # Verificar que .eq se invocó dos veces: id + tenant_id.
        self.assertEqual(chain.eq.call_count, 1)  # primer eq("id", contact_id)
        self.assertEqual(eq_chain.eq.call_count, 1)  # segundo eq("tenant_id", tenant_id)


if __name__ == "__main__":
    unittest.main()
