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

REPO = Path('/home/ansible/workspaces/commerce-ops-platform')
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

    def test_uses_admin_client_for_audit_insert(self):
        # consent_audit_log RLS solo permite INSERT a service_role.
        # El cliente user-auth (cookies) silenciosamente falla.
        # deleteContact debe usar createAdminClient() para el audit.
        self.assertIn(
            "import { createAdminClient } from '@/utils/supabase/admin'",
            self.page_src,
        )
        self.assertIn('createAdminClient()', self.page_src)
        self.assertIn("admin.from('consent_audit_log')", self.page_src)

    def test_aborts_delete_if_audit_fails(self):
        # Audit log es legal-required; si falla, NO procedemos al delete.
        self.assertIn('auditResult.error', self.page_src)
        self.assertIn('NO fue eliminado', self.page_src)

    def test_reads_phone_snapshot_before_delete(self):
        # Antes del DELETE, lee el phone para hashearlo.
        # Patrón: select('phone') → eq('id', contactId) → eq('tenant_id') → single()
        self.assertIn("from('contacts')", self.page_src)
        self.assertIn(".select('phone')", self.page_src)

    def test_inserts_audit_log_with_deleted_event(self):
        self.assertIn("from('consent_audit_log')", self.page_src)
        self.assertIn("event: 'deleted'", self.page_src)

    def test_audit_uses_tenant_console_source(self):
        self.assertIn("source: 'tenant_console'", self.page_src)

    def test_audit_includes_phone_hash(self):
        self.assertIn('phone_hash: hashPhone(', self.page_src)

    def test_audit_includes_actor_email_and_reason(self):
        # Evidence shape:
        #   { reason: reason || null, deleted_by: u?.email ?? null }
        self.assertIn('actor_email: u?.email', self.page_src)
        self.assertIn('reason: reason || null', self.page_src)
        self.assertIn('deleted_by: u?.email', self.page_src)

    def test_audit_runs_before_delete(self):
        # El INSERT en consent_audit_log debe aparecer antes del DELETE
        # físico de la tabla contacts.
        idx_audit = self.page_src.find("from('consent_audit_log')")
        idx_delete_chain = self.page_src.find('.delete()\n      .eq')
        self.assertGreater(idx_audit, 0)
        self.assertGreater(idx_delete_chain, 0)
        self.assertLess(
            idx_audit, idx_delete_chain,
            'INSERT en audit log debe ocurrir ANTES del DELETE físico',
        )

    def test_no_check_constraint_violation_if_no_reason(self):
        # Cuando reason no está, evidence.reason es null (no string vacío)
        # — confirmamos que el código pasa null, no '' (mejor para JSONB query).
        self.assertIn('reason: reason || null', self.page_src)


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
