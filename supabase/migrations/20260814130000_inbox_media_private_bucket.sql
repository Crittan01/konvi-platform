-- =============================================================================
-- G8b fase 1 (auditoría full-stack 2026-08-13) — Bucket PRIVADO para adjuntos
-- de conversación del inbox.
--
-- Hallazgo G8: los adjuntos que el operador envía a clientes vivían en
-- `tenant-media` (public=TRUE) → cualquier persona con la URL podía leerlos
-- (PII potencial: el operador puede adjuntar comprobantes, datos, etc.).
-- Con este bucket los adjuntos dejan de ser públicos; la lectura es por
-- signed URL (fases 2-3: el chat firma al render, el worker firma al enviar
-- a Meta — Meta descarga en el momento del envío, URL con TTL holgado).
--
-- Path convention: {tenant_id}/{conversation_id}/{timestamp}-{rand}.{ext}
--   (foldername(name))[1] = tenant_id — mismo patrón que consent-evidence.
-- Tamaño máximo: 5MB · MIMEs: JPG/PNG/WEBP (imágenes del inbox).
--
-- RLS (patrón consent-evidence, con la diferencia de rol del inbox):
--   • INSERT: cualquier MIEMBRO del tenant (operator incluido — el inbox es
--     herramienta de operadores) en el path de SU tenant.
--   • SELECT: cualquier miembro del tenant.
--   • DELETE: solo owner|manager.
--
-- NO se toca `tenant-media`: las imágenes de catálogo y el logo SIGUEN
-- públicas ahí (el bot las reenvía a clientes por WhatsApp continuamente —
-- Meta exige URL accesible en todo momento, no solo al enviar).
--
-- Forward-only. Idempotente (ON CONFLICT / DROP IF EXISTS).
-- =============================================================================

BEGIN;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'tenant-inbox-media',
    'tenant-inbox-media',
    FALSE,
    5242880,  -- 5 MB
    ARRAY['image/jpeg', 'image/png', 'image/webp']
)
ON CONFLICT (id) DO UPDATE
    SET file_size_limit    = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types,
        public             = EXCLUDED.public;

-- ── INSERT: cualquier miembro del tenant, solo en el path de su tenant. ─────
DROP POLICY IF EXISTS "inbox_media_tenant_write" ON storage.objects;
CREATE POLICY "inbox_media_tenant_write" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'tenant-inbox-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
    );

-- ── SELECT: cualquier miembro del tenant (lectura de objetos; el contenido
--    se sirve por signed URL, que no pasa por RLS de la tabla). ─────────────
DROP POLICY IF EXISTS "inbox_media_tenant_read" ON storage.objects;
CREATE POLICY "inbox_media_tenant_read" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'tenant-inbox-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
    );

-- ── DELETE: solo owner|manager del tenant. ──────────────────────────────────
DROP POLICY IF EXISTS "inbox_media_tenant_delete" ON storage.objects;
CREATE POLICY "inbox_media_tenant_delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'tenant-inbox-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE user_id = auth.uid() AND role IN ('owner', 'manager')
        )
    );

COMMIT;
