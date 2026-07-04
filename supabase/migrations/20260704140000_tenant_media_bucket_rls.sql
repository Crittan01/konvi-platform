-- =============================================================================
-- F7 (2026-07-04) — Bucket 'tenant-media': RLS versionada (bs7/bs14 del audit).
--
-- HALLAZGO: el bucket 'tenant-media' (imágenes de producto + galería) NO tenía
-- policies de aislamiento multi-tenant en NINGUNA migración → el aislamiento
-- dependía de policies creadas a mano en el dashboard, no verificable ni
-- reproducible. Esta migración codifica el contrato.
--
-- Path convention (media-client.tsx:70 / gallery-picker-modal): {tenant_id}/{filename}
-- Bucket PÚBLICO (las fotos de producto se muestran al cliente por WhatsApp vía
-- URL pública → SELECT público es intencional). La ESCRITURA sí es tenant-scoped:
--   • INSERT/UPDATE/DELETE: solo owner|manager del tenant, en SU path {tenant_id}/.
--   • Un tenant NO puede escribir/borrar en la carpeta de otro.
--
-- ⚠️ INTERVENCIÓN HUMANA REQUERIDA antes de aplicar:
--   RESPONSABLE: founder / DBA.
--   PASOS: (1) revisar en el Supabase dashboard si YA existen policies manuales
--     sobre storage.objects para bucket_id='tenant-media' con OTRO nombre (este
--     script solo reemplaza las de nombre 'tenant_media_*'); si existen, borrarlas
--     para evitar policies duplicadas/permisivas. (2) aplicar con el protocolo
--     seguro (supabase db query --linked). (3) `supabase migration repair
--     --status applied 20260704140000`.
--   CRITERIO DE ÉXITO: un authenticated de tenant A recibe 403 al intentar subir
--     a '{tenant_B}/x.jpg'; el operador de A lista/sube en '{tenant_A}/'.
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

-- ── INSERT: solo owner/manager del tenant, en su path {tenant_id}/. ──────────
DROP POLICY IF EXISTS "tenant_media_write" ON storage.objects;
CREATE POLICY "tenant_media_write" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE user_id = auth.uid() AND role IN ('owner', 'manager')
        )
    );

-- ── UPDATE: solo owner/manager del tenant, en su path (upsert/replace). ──────
DROP POLICY IF EXISTS "tenant_media_update" ON storage.objects;
CREATE POLICY "tenant_media_update" ON storage.objects
    FOR UPDATE TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE user_id = auth.uid() AND role IN ('owner', 'manager')
        )
    );

-- ── DELETE: solo owner/manager del tenant, en su path. ──────────────────────
DROP POLICY IF EXISTS "tenant_media_delete" ON storage.objects;
CREATE POLICY "tenant_media_delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE user_id = auth.uid() AND role IN ('owner', 'manager')
        )
    );

-- ── SELECT (list, authenticated): miembro del tenant lista SU carpeta. ──────
-- (La lectura de la imagen por URL sigue siendo pública — bucket public=true.)
DROP POLICY IF EXISTS "tenant_media_list" ON storage.objects;
CREATE POLICY "tenant_media_list" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'tenant-media'
        AND (storage.foldername(name))[1] = (
            SELECT tenant_id::text FROM public.tenant_users
            WHERE user_id = auth.uid() LIMIT 1
        )
    );
