-- =============================================================================
-- F7 (2026-07-04, reescrita 2026-07-05) — Bucket 'tenant-media': RLS versionada.
--
-- HALLAZGO ORIGINAL: el bucket 'tenant-media' NO tenía policies de aislamiento en
-- NINGUNA migración → el aislamiento dependía de policies creadas a mano en el
-- dashboard (`tenant_read_media`/`tenant_upload_media`/`tenant_delete_media`),
-- no verificable ni reproducible. Esta migración codifica el contrato.
--
-- DECISIÓN FOUNDER (2026-07-05): versionar SIN romper. El bucket tiene DOS
-- convenciones de path reales, con modelos de rol distintos:
--
--   (A) Producto / logo / media library → path `{tenant_id}/…`
--       (media-client.tsx / gallery-picker-modal / logo-upload / catalog).
--       Escritura = owner/manager (superficies de catálogo/ajustes, ya gateadas).
--
--   (B) Adjuntos del Inbox → path `inbox-attachments/{tenant_id}/{conversation}/…`
--       (attachment-uploader.tsx:107). Lo opera el rol OPERATOR (persona del
--       Inbox) al enviar imágenes al cliente por WhatsApp → escritura MEMBER-level
--       (cualquier miembro del tenant), NO restringida a owner/manager.
--
-- Se descartó la versión owner/manager-para-todo: habría bloqueado a los
-- operadores el envío de imágenes por el Inbox. Se descartó dejar las policies
-- manuales: no versionadas + no cubrían la convención (B).
--
-- Bucket PÚBLICO (las fotos se muestran al cliente por URL pública → SELECT por
-- URL es intencional y no depende de RLS). La ESCRITURA sí es tenant-scoped:
-- cada tenant solo escribe en SU carpeta ({tenant_id}/ o inbox-attachments/{tenant_id}/).
-- service_role (cron/API/offboarding purge) bypassa RLS → no afectado.
--
-- Resolución de identidad: JWT `app_metadata.tenant_id` + `app_metadata.role`
-- (mismo criterio que 20260704156010_f6_rls_role_hardening — fuente única del
-- rol/tenant en sesión). Idempotente (DROP IF EXISTS + CREATE).
--
-- ⚠️ Reemplaza las policies manuales `tenant_*_media` por las versionadas
--   `tenant_media_*`. Si existen OTRAS policies manuales con nombre distinto sobre
--   storage.objects para bucket_id='tenant-media', revisarlas en el dashboard.
-- =============================================================================

-- Asegura el bucket (público, límite e imágenes) — idempotente.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'tenant-media',
    'tenant-media',
    TRUE,
    10485760,  -- 10 MB
    ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE
    SET file_size_limit    = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types,
        public             = EXCLUDED.public;

-- Retira las policies manuales previas (nombre divergente) para que NO se OR-combinen
-- con las versionadas (RLS es permisiva: dejarlas anularía el endurecimiento por rol).
DROP POLICY IF EXISTS "tenant_read_media"   ON storage.objects;
DROP POLICY IF EXISTS "tenant_upload_media" ON storage.objects;
DROP POLICY IF EXISTS "tenant_delete_media" ON storage.objects;
-- Y las versionadas (idempotencia ante reejecución).
DROP POLICY IF EXISTS "tenant_media_select_member"     ON storage.objects;
DROP POLICY IF EXISTS "tenant_media_write_privileged"  ON storage.objects;
DROP POLICY IF EXISTS "tenant_media_update_privileged" ON storage.objects;
DROP POLICY IF EXISTS "tenant_media_delete_privileged" ON storage.objects;
DROP POLICY IF EXISTS "tenant_media_inbox_write"       ON storage.objects;

-- ── (A) Producto/logo/media — SELECT (list) por miembro del tenant. ──────────
-- (La lectura de la imagen por URL sigue siendo pública — bucket public=true.)
CREATE POLICY "tenant_media_select_member" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')
    );

-- ── (A) Producto/logo/media — INSERT solo owner/manager, en su carpeta. ──────
CREATE POLICY "tenant_media_write_privileged" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- ── (A) Producto/logo/media — UPDATE (upsert/replace) owner/manager. ─────────
CREATE POLICY "tenant_media_update_privileged" ON storage.objects
    FOR UPDATE TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- ── (A) Producto/logo/media — DELETE owner/manager. ─────────────────────────
CREATE POLICY "tenant_media_delete_privileged" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- ── (B) Adjuntos del Inbox — INSERT MEMBER-level (operadores envían imágenes). ─
-- Path: inbox-attachments/{tenant_id}/{conversation}/…  → foldername[1]='inbox-attachments',
-- foldername[2]=tenant_id. Cualquier miembro del tenant (incl. operator) puede subir
-- EN SU tenant; no puede escribir en la carpeta de otro tenant.
CREATE POLICY "tenant_media_inbox_write" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = 'inbox-attachments'
        AND (storage.foldername(name))[2] = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')
    );
