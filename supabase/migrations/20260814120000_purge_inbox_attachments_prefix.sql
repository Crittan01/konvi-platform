-- G8a (auditoría full-stack 2026-08-13) — erasure incompleto de adjuntos inbox.
--
-- Hallazgo: los adjuntos de imagen del inbox viven en
--   tenant-media/inbox-attachments/{tenant_id}/{conversation_id}/{archivo}
-- y fn_purge_tenant_storage_objects solo borraba el prefijo '{tenant_id}/%' →
-- esos objetos SOBREVIVÍAN al hard-delete del tenant (fuga PII post-erasure,
-- Ley 1581 / Habeas Data). Ahora la RPC borra AMBOS prefijos del bucket.
--
-- Forward-only (no se toca la migración original). Degrada seguro igual que
-- antes (sin schema storage → 0). Misma postura de grants.

BEGIN;

CREATE OR REPLACE FUNCTION public.fn_purge_tenant_storage_objects(
    p_tenant_id  UUID,
    p_bucket_ids TEXT[] DEFAULT ARRAY['tenant-media']::TEXT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_buckets TEXT[];
BEGIN
    IF p_tenant_id IS NULL THEN
        RAISE EXCEPTION 'p_tenant_id es obligatorio' USING ERRCODE = '40000';
    END IF;

    -- Degrada seguro si Storage no está instalado en este entorno.
    IF to_regclass('storage.objects') IS NULL THEN
        RETURN 0;
    END IF;

    -- Default + exclusión defensiva del bucket de archivo legal (nunca purgarlo).
    v_buckets := COALESCE(p_bucket_ids, ARRAY['tenant-media']::TEXT[]);
    v_buckets := ARRAY(
        SELECT DISTINCT b
          FROM unnest(v_buckets) AS b
         WHERE b IS NOT NULL
           AND b <> 'offboarding-archive'
    );

    IF array_length(v_buckets, 1) IS NULL THEN
        RETURN 0;
    END IF;

    -- El trigger storage.protect_delete exige storage.allow_delete_query='true'
    -- en la sesión (protección anti-borrado-accidental de Supabase, verificado
    -- en prod 2026-08-14). La RPC es la vía autorizada de erasure → lo fija
    -- LOCAL a su transacción (se revierte al commit; sin efecto fuera).
    PERFORM set_config('storage.allow_delete_query', 'true', true);

    -- Borra AMBOS prefijos del tenant (G8a): '{tenant_id}/%' (media library,
    -- logo) e 'inbox-attachments/{tenant_id}/%' (adjuntos de conversación).
    -- El '/' evita colisión con otro tenant cuyo id sea prefijo de éste.
    DELETE FROM storage.objects o
     WHERE o.bucket_id = ANY(v_buckets)
       AND (
             o.name LIKE (p_tenant_id::TEXT || '/%')
          OR o.name LIKE ('inbox-attachments/' || p_tenant_id::TEXT || '/%')
       );

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION public.fn_purge_tenant_storage_objects IS
    'F6 erasure + G8a — borra filas de storage.objects con name "{tenant_id}/%" '
    'o "inbox-attachments/{tenant_id}/%" en los buckets dados (default '
    'tenant-media). Excluye offboarding-archive. Degrada seguro sin schema '
    'storage. La purga FÍSICA del blob la completa scripts/admin/purge_tenant_storage.py. '
    'Idempotente.';

GRANT EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects FROM authenticated;

COMMIT;
