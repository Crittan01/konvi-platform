-- =============================================================================
-- Rev. 109 (J.2.4.4 Fase 2) — Hard-delete + cold archive bucket
--
-- Contexto: Fase 1 (migration 20260616000000) creó la infraestructura para
-- soft-delete + 30d grace. Esta migration agrega:
--   1. Bucket Storage 'offboarding-archive' para preservar audit + consent
--      en cold storage 5 años (Art. 22 Ley 1581 deber custodia).
--   2. RPC fn_hard_delete_tenant que ejecuta DELETE atómico tras snapshot.
--   3. RPC fn_list_tenants_pending_hard_delete que el cron consulta.
--
-- Estrategia hard-delete:
--   1. Worker cron (cada 6h) consulta tenants WHERE deletion_scheduled_for
--      <= NOW() AND deleted_at IS NULL via fn_list_tenants_pending_hard_delete.
--   2. Para c/u: app-layer snapshot a Storage bucket (audit_log +
--      consent_audit_log + tenant_offboarding_log + tenant_legal_acceptance).
--   3. Tras snapshot exitoso, invoca fn_hard_delete_tenant que ejecuta
--      DELETE FROM tenants (CASCADE limpia tablas hijas) + marca deleted_at.
--   4. Log evento 'hard_deleted' en tenant_offboarding_log (tabla sobrevive
--      por no tener FK CASCADE — diseño Fase 1).
-- =============================================================================

-- 1. Storage bucket 'offboarding-archive' con RLS service_role-only.
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES (
    'offboarding-archive',
    'offboarding-archive',
    FALSE,                              -- NO público — solo service_role
    52428800                            -- 50 MB por archive (suficiente para tenants medianos)
)
ON CONFLICT (id) DO UPDATE
   SET public = FALSE;                  -- Defensivo: si alguien lo creó público, forzar privado.


-- RLS policies — solo service_role lee/escribe. NUNCA authenticated/anon.
DO $$
BEGIN
    -- SELECT policy
    IF NOT EXISTS (
        SELECT 1 FROM pg_policy
         WHERE polname = 'offboarding_archive_service_role_select'
    ) THEN
        CREATE POLICY offboarding_archive_service_role_select
            ON storage.objects
            FOR SELECT
            TO service_role
            USING (bucket_id = 'offboarding-archive');
    END IF;

    -- INSERT policy
    IF NOT EXISTS (
        SELECT 1 FROM pg_policy
         WHERE polname = 'offboarding_archive_service_role_insert'
    ) THEN
        CREATE POLICY offboarding_archive_service_role_insert
            ON storage.objects
            FOR INSERT
            TO service_role
            WITH CHECK (bucket_id = 'offboarding-archive');
    END IF;
END $$;


-- 2. RPC: listar tenants pending hard-delete (consultado por cron).
CREATE OR REPLACE FUNCTION public.fn_list_tenants_pending_hard_delete(
    p_limit INTEGER DEFAULT 50
)
RETURNS TABLE (
    tenant_id              UUID,
    deletion_scheduled_for TIMESTAMPTZ,
    deletion_requested_at  TIMESTAMPTZ,
    grace_period_days      INTEGER
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        t.id AS tenant_id,
        t.deletion_scheduled_for,
        t.deletion_requested_at,
        EXTRACT(DAY FROM (t.deletion_scheduled_for - t.deletion_requested_at))::INTEGER
            AS grace_period_days
      FROM public.tenants t
     WHERE t.deletion_scheduled_for IS NOT NULL
       AND t.deletion_scheduled_for <= NOW()
       AND t.deleted_at IS NULL
     ORDER BY t.deletion_scheduled_for ASC
     LIMIT p_limit;
$$;

COMMENT ON FUNCTION public.fn_list_tenants_pending_hard_delete IS
    'F.10 + J.2.4.4 Fase 2 — invocado hourly por worker. Lista tenants '
    'cuyo grace period venció (deletion_scheduled_for <= NOW()) y aún no '
    'fueron hard-deleted. Worker hace snapshot + invoca fn_hard_delete_tenant.';

GRANT EXECUTE ON FUNCTION public.fn_list_tenants_pending_hard_delete TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_list_tenants_pending_hard_delete FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_list_tenants_pending_hard_delete FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_list_tenants_pending_hard_delete FROM anon;


-- 3. RPC: hard-delete atómico del tenant.
--    Pre-condición: worker debe HABER hecho snapshot a bucket BEFORE invocar.
--    Esta función NO valida snapshot (responsabilidad caller) — solo ejecuta
--    DELETE con FOR UPDATE lock para evitar race + marca deleted_at.
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
    sched   TIMESTAMPTZ;
    already TIMESTAMPTZ;
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
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
        jsonb_build_object(
            'archive_path', p_archive_path,
            'evidence', p_evidence,
            'deleted_at', NOW()
        )
    );

    -- 4. DELETE FROM tenants — CASCADE limpia todo lo que tenga FK ON DELETE CASCADE.
    --    Lo que NO tiene CASCADE (tenant_offboarding_log) sobrevive intencionalmente.
    DELETE FROM public.tenants WHERE id = p_tenant_id;

    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION public.fn_hard_delete_tenant IS
    'J.2.4.4 Fase 2 — Hard-delete atómico del tenant. Pre-condición: caller '
    '(worker) debe haber subido snapshot del audit_log/consent/legal a '
    'Storage bucket "offboarding-archive" ANTES de invocar. Logs eventos '
    '"archived" + "hard_deleted" en tenant_offboarding_log (sobrevive '
    'CASCADE). Idempotente: si ya fue deleted, retorna FALSE sin error.';

GRANT EXECUTE ON FUNCTION public.fn_hard_delete_tenant TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_hard_delete_tenant FROM anon;
