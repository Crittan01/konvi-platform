-- =============================================================================
-- F6 — Erasure completeness: purga de objetos de Storage en el hard-delete.
--
-- Gap (audit F6 offboarding, sev ALTO — contradice "erasure 100% completa"):
-- fn_hard_delete_tenant (20260617000000) ejecuta DELETE FROM tenants con
-- CASCADE sobre ~50 tablas hijas, PERO el CASCADE NO alcanza storage.objects:
-- esa tabla no tiene FK a public.tenants. Resultado: tras el hard-delete
-- "irreversible" los archivos subidos por el tenant y por sus clientes
-- (bucket tenant-media/{tenant_id}/...) permanecen en Storage con PII →
-- erasure legalmente INCOMPLETA (Ley 1581 Art. 16 derecho de eliminación).
--
-- Fix (defense-in-depth, 2 capas):
--   1. RPC fn_purge_tenant_storage_objects(tenant_id, bucket_ids[]) — borra las
--      filas de storage.objects cuyo name empieza por '{tenant_id}/' en los
--      buckets indicados. Transaccional y verificable a nivel DB.
--   2. fn_hard_delete_tenant se extiende (CREATE OR REPLACE) para invocar la
--      purga ANTES del DELETE FROM tenants, dejando evidencia del conteo en el
--      log 'hard_deleted'.
--
-- NOTA — purga FÍSICA del blob:
--   Borrar la fila de storage.objects deja el objeto inaccesible/no-listable,
--   pero la recolección del blob físico depende del backend de Storage y NO
--   está garantizada por SQL. La purga físicamente completa (elimina blob + fila
--   vía Storage API .remove) la ejecuta scripts/admin/purge_tenant_storage.py.
--   Ambas capas comparten el mismo criterio de prefijo por tenant.
--
-- LISTA DE BUCKETS: el default parametrizado es ARRAY['tenant-media'] (único
--   bucket con PII per-tenant conocido hoy). La lista canónica COMPLETA de
--   buckets con PII la confirma el founder (external_blocked) y se pasa como
--   p_bucket_ids sin cambiar el mecanismo. NUNCA incluir 'offboarding-archive'
--   (debe sobrevivir 5 años, Art. 22) — la función lo excluye defensivamente.
--
-- NO se auto-aplica (política F6/F7: la migración se crea, el founder la revisa
-- y la aplica sobre el remote productivo — el ledger tiene drift). Idempotente:
-- CREATE OR REPLACE + guardas por existencia; re-ejecutarla es seguro.
-- =============================================================================

BEGIN;

-- 1. RPC: purga de objetos de Storage por prefijo de tenant.
--    Borra storage.objects.name LIKE '{tenant_id}/%' en los buckets indicados.
--    Degrada seguro: si el schema storage no existe (entornos sin Storage),
--    retorna 0 sin error. SECURITY DEFINER: corre como owner de la función,
--    que sí puede borrar de storage.objects (bypass de RLS de storage).
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

    -- Borra por prefijo '{tenant_id}/'. El '/' evita colisión con otro tenant
    -- cuyo id sea prefijo de éste (los UUID tienen longitud fija, pero el '/'
    -- lo hace robusto ante cualquier convención de path).
    DELETE FROM storage.objects o
     WHERE o.bucket_id = ANY(v_buckets)
       AND o.name LIKE (p_tenant_id::TEXT || '/%');

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION public.fn_purge_tenant_storage_objects IS
    'F6 erasure — borra filas de storage.objects con name "{tenant_id}/%" en '
    'los buckets dados (default tenant-media). Excluye offboarding-archive. '
    'Degrada seguro sin schema storage. La purga FÍSICA del blob la completa '
    'scripts/admin/purge_tenant_storage.py (Storage API). Idempotente.';

GRANT EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_purge_tenant_storage_objects FROM anon;


-- 2. fn_hard_delete_tenant — reemplazo idéntico al de 20260617000000 salvo el
--    nuevo paso 3.5 (purga de Storage) + su conteo en el evidence del log.
CREATE OR REPLACE FUNCTION public.fn_hard_delete_tenant(
    p_tenant_id      UUID,
    p_archive_path   TEXT,
    p_evidence       JSONB DEFAULT '{}'::jsonb
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    sched            TIMESTAMPTZ;
    already          TIMESTAMPTZ;
    v_storage_purged INTEGER := 0;
BEGIN
    -- Lock fila + validar que es elegible.
    SELECT deletion_scheduled_for, deleted_at
      INTO sched, already
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF sched IS NULL THEN
        RAISE EXCEPTION
            'Tenant % NO tiene deletion_scheduled_for — no es elegible para hard-delete',
            p_tenant_id
            USING ERRCODE = '40000';
    END IF;

    IF already IS NOT NULL THEN
        -- Ya fue hard-deleted antes (idempotencia: cron pudo re-invocar).
        RETURN FALSE;
    END IF;

    IF sched > NOW() THEN
        RAISE EXCEPTION
            'Tenant % todavía en grace period (scheduled_for=%, NOW=%)',
            p_tenant_id, sched, NOW()
            USING ERRCODE = '40000';
    END IF;

    -- 1. Log evento 'archived' ANTES de borrar.
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'archived', NULL, 'cron@worker', NULL,
        jsonb_build_object(
            'archive_path', p_archive_path,
            'archived_at', NOW()
        )
    );

    -- 2. Marcar deleted_at PRIMERO (audit trail incluso si cascade falla).
    --    NOTA: tenants es la fila principal — el CASCADE limpia ~50 tablas hijas.
    UPDATE public.tenants
       SET deleted_at = NOW()
     WHERE id = p_tenant_id;

    -- 3. Log evento 'hard_deleted' ANTES del DELETE — el log sobrevive
    --    porque tenant_offboarding_log NO tiene FK CASCADE a tenants.
    --    (Se re-loguea el conteo de storage tras la purga en el paso 3.5).
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
        jsonb_build_object(
            'archive_path', p_archive_path,
            'evidence', p_evidence,
            'deleted_at', NOW()
        )
    );

    -- 3.5. Purga de objetos de Storage con PII del tenant (bucket tenant-media
    --      y cualquier otro bucket per-tenant). El CASCADE de tenants NO alcanza
    --      storage.objects → sin esto la PII de clientes queda en Storage.
    --      Best-effort: si algo falla, se registra pero NO se aborta el delete
    --      (compliance Art. 16 prioriza que el borrado del tenant se complete).
    BEGIN
        v_storage_purged := public.fn_purge_tenant_storage_objects(
            p_tenant_id, ARRAY['tenant-media']::TEXT[]
        );
        PERFORM public.fn_log_tenant_offboarding_event(
            p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
            jsonb_build_object(
                'storage_objects_purged', v_storage_purged,
                'storage_buckets', ARRAY['tenant-media'],
                'note', 'purga DB de storage.objects; blob físico via admin script'
            )
        );
    EXCEPTION WHEN OTHERS THEN
        PERFORM public.fn_log_tenant_offboarding_event(
            p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
            jsonb_build_object(
                'storage_purge_error', SQLERRM,
                'note', 'purga de Storage falló; requiere purga manual via admin script'
            )
        );
    END;

    -- 4. DELETE FROM tenants — CASCADE limpia todo lo que tenga FK ON DELETE CASCADE.
    --    Lo que NO tiene CASCADE (tenant_offboarding_log) sobrevive intencionalmente.
    DELETE FROM public.tenants WHERE id = p_tenant_id;

    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION public.fn_hard_delete_tenant IS
    'J.2.4.4 Fase 2 + F6 — Hard-delete atómico del tenant. Pre-condición: caller '
    '(worker) debe haber subido snapshot del audit_log/consent/legal a '
    'Storage bucket "offboarding-archive" ANTES de invocar. Purga storage.objects '
    'con PII del tenant (fn_purge_tenant_storage_objects, best-effort) antes del '
    'DELETE. Logs "archived" + "hard_deleted" en tenant_offboarding_log (sobrevive '
    'CASCADE). Idempotente: si ya fue deleted, retorna FALSE sin error.';

GRANT EXECUTE ON FUNCTION public.fn_hard_delete_tenant TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM anon;

COMMIT;
