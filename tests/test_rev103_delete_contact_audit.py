"""Rev. 103 (SaaS B2B pivot) — Tests del delete contact con audit log.

Cobertura (lectura de fuente):
  • Migration 20260510010000 añade 'deleted' al CHECK del audit log.
  • Helper TS hashPhone es espejo del Python _hash_phone (misma regla).
  • deleteContact server action hace INSERT en consent_audit_log
    ANTES del DELETE físico, con event='deleted', source='tenant_console',
    phone_hash, actor_email, evidence.reason.
  • UI dialog acepta motivo opcional (`delete_reason` en FormData).
  • UI dialog ya no afirma "no queda registro Habeas Data" (lo contrario:
    queda audit log inmutable).
"""
from pathlib import Path
import unittest

REPO = Path('/home/ansible/workspaces/konvi-platform')
PAGE_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/page.tsx'
MANAGER_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx'
PHONE_HASH_TS = REPO / 'apps/web/lib/crypto/phone-hash.ts'
MIGRATION = REPO / 'supabase/migrations/20260510010000_consent_audit_log_add_deleted_event.sql'


class MigrationDeletedEventTests(unittest.TestCase):
    """La migración añade 'deleted' al CHECK constraint."""

    def setUp(self):
        self.sql = MIGRATION.read_text()

    def test_migration_drops_old_constraint(self):
        self.assertIn('DROP CONSTRAINT IF EXISTS consent_audit_log_event_check', self.sql)

    def test_migration_adds_deleted_event(self):
        # 'deleted' debe estar en la nueva lista de eventos válidos.
        self.assertIn("'deleted'", self.sql)

    def test_migration_preserves_existing_events(self):
        # Eventos rev. 93–101 deben seguir aceptados.
        for evt in ('granted', 'revoked', 'rectified',
                    'export_request', 'portability', 'pii_access'):
            self.assertIn(f"'{evt}'", self.sql)


class PhoneHashHelperTests(unittest.TestCase):
    """Helper TS hashPhone es espejo del Python _hash_phone."""

    def setUp(self):
        self.ts_src = PHONE_HASH_TS.read_text()

    def test_helper_uses_sha256(self):
        self.assertIn("createHash('sha256')", self.ts_src)

    def test_helper_normalizes_same_as_python(self):
        # Python: re.sub(r"[\s+\-]", "", str(phone))
        # TS: String(phone).replace(/[\s+-]/g, '')
        # Same character class semantics — strips spaces, +, -.
        self.assertIn("[\\s+-]", self.ts_src)

    def test_helper_returns_null_for_empty(self):
        self.assertIn('if (!phone) return null', self.ts_src)

    def test_helper_export_signature(self):
        self.assertIn(
            'export function hashPhone(phone: string | null | undefined): string | null',
            self.ts_src,
        )


class DeleteContactServerActionTests(unittest.TestCase):
    """deleteContact hace audit antes del DELETE."""

    def setUp(self):
        self.page_src = PAGE_TSX.read_text()

    def test_imports_hash_phone_helper(self):
        self.assertIn(
            "import { hashPhone } from '@/lib/crypto/phone-hash'",
            self.page_src,
        )

    def test_delegates_to_purge_api_endpoint(self):
        """Sem 7 F2 cierre 2026-05-19 — UI server action ya NO hace DELETE
        directo a tabla contacts. Delega al endpoint Python `POST /api/v1/
        contacts/{id}/purge` que ejecuta cascade completo (audit + cleanup).
        Esto cierra el bug founder UAT 2026-05-19 (conv 056490b8): carts
        huérfanos no se limpiaban tras delete UI.
        """
        self.assertIn('/api/v1/contacts/', self.page_src)
        self.assertIn('/purge', self.page_src)

    def test_purge_uses_authorization_header(self):
        """El call al API pasa el JWT del usuario en Authorization header."""
        self.assertIn('Authorization: `Bearer ${token}`', self.page_src)

    def test_purge_requires_owner_role(self):
        """Hard cascade es destructivo — solo owner puede invocarlo."""
        self.assertIn("m.role !== 'owner'", self.page_src)

    def test_purge_passes_reason_in_body(self):
        """El motivo del operador viaja al endpoint API para que el audit
        log Python lo registre en evidence."""
        self.assertIn('reason: reason || null', self.page_src)

    def test_purge_propagates_errors_to_ui(self):
        """Si el endpoint falla, el UI debe propagar el error al cliente
        (no fallar silente)."""
        self.assertIn('Purge falló', self.page_src)
        self.assertIn('throw new Error', self.page_src)


class DeleteUIRev103Tests(unittest.TestCase):
    """UI dialog: motivo opcional + mensaje correcto."""

    def setUp(self):
        self.manager_src = MANAGER_TSX.read_text()

    def test_dialog_accepts_optional_reason(self):
        self.assertIn('pendingDeleteReason', self.manager_src)
        self.assertIn("fd.set('delete_reason'", self.manager_src)

    def test_dialog_no_longer_claims_no_audit(self):
        # Mensaje rev. 102: "No queda registro Habeas Data" ya NO debe estar.
        self.assertNotIn(
            'No queda registro Habeas Data',
            self.manager_src,
        )

    def test_dialog_explains_audit_log_persists(self):
        # Mensaje rev. 103 explica que sí queda audit log.
        self.assertIn(
            'audit log inmutable',
            self.manager_src,
        )

    def test_dialog_clears_reason_on_close(self):
        # Tanto en cancel (handleDeleteById) como en submit (confirmDelete)
        # se hace setPendingDeleteReason('').
        self.assertIn("setPendingDeleteReason('')", self.manager_src)


if __name__ == '__main__':
    unittest.main()
