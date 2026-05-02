"""Rev. 103 (F10) — Tests del upload de evidencia física a Storage.

Cobertura (lectura de fuente — no E2E con Storage real):
  • Migración crea bucket privado consent-evidence con RLS por tenant.
  • Helper uploadConsentEvidence valida MIME + size antes de subir.
  • addContact wire: insert .select('id') → upload si in_person → update.
  • editContact wire: si in_person + file → upload → merge URL.
  • UI: input file aparece solo cuando canal=in_person (form Add + Edit).
"""
from pathlib import Path
import unittest

REPO = Path('/home/ansible/workspaces/commerce-ops-platform')
PAGE_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/page.tsx'
MANAGER_TSX = REPO / 'apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx'
UPLOAD_HELPER = REPO / 'apps/web/app/dashboard/(sales)/contacts/_components/helpers/upload-evidence.ts'
MIGRATION = REPO / 'supabase/migrations/20260510020000_consent_evidence_bucket.sql'


class BucketMigrationTests(unittest.TestCase):
    """Migración crea bucket consent-evidence con RLS por tenant."""

    def setUp(self):
        self.sql = MIGRATION.read_text()

    def test_creates_private_bucket(self):
        self.assertIn("'consent-evidence'", self.sql)
        self.assertIn('public, file_size_limit', self.sql)
        # FALSE = bucket privado (RLS aplica).
        self.assertIn('FALSE,', self.sql)

    def test_size_limit_5mb(self):
        # 5 * 1024 * 1024 = 5242880
        self.assertIn('5242880', self.sql)

    def test_allowed_mimes_pdf_and_images(self):
        for mime in ("'application/pdf'", "'image/jpeg'", "'image/png'", "'image/webp'"):
            self.assertIn(mime, self.sql)

    def test_rls_insert_owner_or_manager(self):
        self.assertIn('consent_evidence_tenant_write', self.sql)
        self.assertIn("role IN ('owner', 'manager')", self.sql)

    def test_rls_select_any_member(self):
        self.assertIn('consent_evidence_tenant_read', self.sql)

    def test_rls_uses_tenant_path_prefix(self):
        # storage.foldername(name)[1] = tenant_id::text
        self.assertIn('storage.foldername(name)', self.sql)


class UploadHelperTests(unittest.TestCase):
    """uploadConsentEvidence valida y sube al bucket."""

    def setUp(self):
        self.ts = UPLOAD_HELPER.read_text()

    def test_marks_file_use_server(self):
        # Server actions son safe-list — el helper debe marcar 'use server'.
        self.assertIn("'use server'", self.ts)

    def test_size_limit_constant(self):
        # `'use server'` files only allow async exports, so estos consts
        # son module-private (no exportados).
        self.assertIn('CONSENT_EVIDENCE_MAX_SIZE_BYTES', self.ts)
        self.assertIn('5 * 1024 * 1024', self.ts)

    def test_allowed_mimes_constant(self):
        self.assertIn('CONSENT_EVIDENCE_ALLOWED_MIMES', self.ts)
        for mime in ("'application/pdf'", "'image/jpeg'", "'image/png'", "'image/webp'"):
            self.assertIn(mime, self.ts)

    def test_returns_skipped_for_no_file(self):
        self.assertIn("status: 'skipped'", self.ts)

    def test_rejects_too_large(self):
        self.assertIn("'too_large'", self.ts)

    def test_rejects_bad_mime(self):
        self.assertIn("'mime_not_allowed'", self.ts)

    def test_uses_tenant_contact_path_convention(self):
        # path = `${tenantId}/${contactId}/${Date.now()}-${safeName}`
        self.assertIn('${tenantId}/${contactId}/', self.ts)

    def test_sanitizes_filename(self):
        # Reemplaza chars no seguros por _
        self.assertIn("replace(/[^A-Za-z0-9._-]+/g, '_')", self.ts)

    def test_returns_public_url_after_upload(self):
        self.assertIn('getPublicUrl', self.ts)


class ServerActionWireTests(unittest.TestCase):
    """addContact y editContact invocan uploadConsentEvidence."""

    def setUp(self):
        self.page_src = PAGE_TSX.read_text()

    def test_imports_upload_helper(self):
        self.assertIn(
            "import { uploadConsentEvidence } from './_components/helpers/upload-evidence'",
            self.page_src,
        )

    def test_add_uses_select_id_single_to_get_new_id(self):
        # await sb.from('contacts').insert({...}).select('id').single()
        self.assertIn(".select('id').single()", self.page_src)

    def test_add_only_uploads_when_in_person_and_consent(self):
        # if (newId && consentGiven && consentSource === 'in_person')
        self.assertIn(
            "newId && consentGiven && consentSource === 'in_person'",
            self.page_src,
        )

    def test_edit_only_uploads_when_in_person(self):
        self.assertIn(
            "editContactId && consentSource === 'in_person'",
            self.page_src,
        )

    def test_persists_attachment_url_in_evidence(self):
        # mergedEvidence.attachment_url = upload.url
        self.assertIn('attachment_url', self.page_src)
        self.assertIn('attachment_path', self.page_src)
        self.assertIn('attachment_uploaded_at', self.page_src)

    def test_too_large_throws_human_error(self):
        self.assertIn('supera 5 MB', self.page_src)


class UIRev103UploadTests(unittest.TestCase):
    """UI muestra input file solo cuando canal=in_person."""

    def setUp(self):
        self.manager_src = MANAGER_TSX.read_text()

    def test_add_form_input_file_conditional_in_person(self):
        # Only renderiza cuando addConsentChecked + addConsentSource === 'in_person'
        self.assertIn(
            "addConsentChecked && addConsentSource === 'in_person'",
            self.manager_src,
        )

    def test_edit_form_input_file_conditional_in_person(self):
        # En edit, evalúa contra currentSource === 'in_person'.
        self.assertIn(
            "currentSource === 'in_person'",
            self.manager_src,
        )

    def test_file_input_name_matches_helper(self):
        # name="consent_evidence_file" coincide con formData.get del helper.
        self.assertIn('name="consent_evidence_file"', self.manager_src)

    def test_accept_attribute_matches_allowed_mimes(self):
        # accept=".pdf,application/pdf,image/jpeg,image/png,image/webp"
        self.assertIn('accept=".pdf,application/pdf,image/jpeg,image/png,image/webp"', self.manager_src)

    def test_edit_shows_existing_attachment_link(self):
        self.assertIn('existingAttachmentUrl', self.manager_src)
        self.assertIn('Ver archivo actual', self.manager_src)


if __name__ == '__main__':
    unittest.main()
