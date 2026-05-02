-- =============================================================================
-- Rev. 103 (F10) — Bucket privado para evidencias físicas de consent.
--
-- Caso de uso: cuando canal=in_person, el operador puede adjuntar el
-- escaneo del documento firmado por el titular. Hoy ese papel se
-- referencia como texto libre en consent_evidence.note (frágil); con
-- el bucket queda guardado en Storage con URL en consent_evidence.attachment_url.
--
-- Path convention: {tenant_id}/{contact_id}/{timestamp}-{filename}
-- Tamaño máximo: 5MB · MIMEs: PDF + JPG/PNG/WEBP
--
-- RLS:
--   • INSERT: solo owner|manager del tenant en el path correcto.
--   • SELECT: cualquier miembro del tenant (operator incluido) puede ver.
--
-- SAR export incluye attachment_url automáticamente vía consent_evidence.
-- =============================================================================

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'consent-evidence',
    'consent-evidence',
    FALSE,
    5242880,  -- 5 MB
    ARRAY[
        'application/pdf',
        'image/jpeg',
        'image/png',
        'image/webp'
    ]
)
ON CONFLICT (id) DO UPDATE
    SET file_size_limit    = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types,
        public             = EXCLUDED.public;

-- ── RLS — INSERT: solo owner/manager del tenant en su path. ─────────────────
DROP POLICY IF EXISTS "consent_evidence_tenant_write" ON storage.objects;
CREATE POLICY "consent_evidence_tenant_write" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'consent-evidence'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text
            FROM public.tenant_users
            WHERE user_id = auth.uid()
            LIMIT 1
        )
        AND EXISTS (
            SELECT 1
            FROM public.tenant_users
            WHERE user_id = auth.uid()
              AND role IN ('owner', 'manager')
        )
    );

-- ── RLS — SELECT: cualquier miembro del tenant puede listar/leer. ───────────
DROP POLICY IF EXISTS "consent_evidence_tenant_read" ON storage.objects;
CREATE POLICY "consent_evidence_tenant_read" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'consent-evidence'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text
            FROM public.tenant_users
            WHERE user_id = auth.uid()
            LIMIT 1
        )
    );

-- ── RLS — DELETE: solo owner/manager (ej. limpieza tras hard-delete contact).
DROP POLICY IF EXISTS "consent_evidence_tenant_delete" ON storage.objects;
CREATE POLICY "consent_evidence_tenant_delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'consent-evidence'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text
            FROM public.tenant_users
            WHERE user_id = auth.uid()
            LIMIT 1
        )
        AND EXISTS (
            SELECT 1
            FROM public.tenant_users
            WHERE user_id = auth.uid()
              AND role IN ('owner', 'manager')
        )
    );
