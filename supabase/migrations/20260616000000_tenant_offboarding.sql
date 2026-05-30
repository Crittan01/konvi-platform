-- =============================================================================
-- Rev. 109 (J.2.4.4) — Tenant offboarding workflow
--
-- Contexto: Habeas Data Ley 1581 Colombia exige:
--   - Art. 16: derecho de eliminación (tenant puede solicitar cierre de cuenta).
--   - Art. 22: deber de custodia trazabilidad post-cierre (audit_log + consent
--     deben preservarse 5 años para responder a SIC).
--
-- Diseño:
--   - Soft-delete con grace period 30d. Tenant solicita cierre → cuenta queda
--     en lectura-solo + cron hace hard-delete tras 30d (cancelable por owner).
--   - Cold archive: antes de hard-delete, snapshot de audit_log +
--     consent_audit_log + tenant_offboarding_log a storage bucket
--     'offboarding-archive' (retention 5y, RLS service_role-only).
--   - Hard-delete usa FK CASCADE en la mayoría de tablas; algunas
--     (audit_log + consent_audit_log) se PRESERVAN en archive antes del delete.
--
-- Cumplimiento Habeas Data complementario al SAR contact-level rev93-99:
--   - SAR existente cubre data subject (cliente final del tenant).
--   - Este flujo cubre tenant-level (la empresa que opera la plataforma).
-- =============================================================================

-- 1. Columnas nuevas en tenants para el lifecycle del offboarding.
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS deletion_requested_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deletion_scheduled_for TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deletion_requested_by  UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS deletion_reason        TEXT,
    ADD COLUMN IF NOT EXISTS deleted_at             TIMESTAMPTZ;

COMMENT ON COLUMN public.tenants.deletion_requested_at IS
    'Cuando el owner solicitó offboarding. NULL = activo. Soft-delete arranca aquí.';
COMMENT ON COLUMN public.tenants.deletion_scheduled_for IS
    'Cuando el cron hard-deletea el tenant (típico: requested_at + 30d).';
COMMENT ON COLUMN public.tenants.deletion_requested_by IS
    'Usuario que originó el offboarding (auth.users.id).';
COMMENT ON COLUMN public.tenants.deletion_reason IS
    'Razón textual del owner. Persistida para auditoría SIC.';
COMMENT ON COLUMN public.tenants.deleted_at IS
    'Cuando el cron ejecutó hard-delete. NULL = aún recoverable.';


-- 2. Índice parcial para el cron — solo escanea tenants con deletion programada.
CREATE INDEX IF NOT EXISTS tenants_deletion_scheduled_idx
    ON public.tenants (deletion_scheduled_for)
 WHERE deletion_scheduled_for IS NOT NULL
   AND deleted_at IS NULL;


-- 3. Tabla append-only de eventos del offboarding (evidencia forense Ley 1581).
CREATE TABLE IF NOT EXISTS public.tenant_offboarding_log (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         UUID NOT NULL,
        -- NO FK ON DELETE CASCADE — debemos preservar el log incluso post-hard-delete.
        -- Pero sí guardamos tenant_id para correlación.
    event             TEXT NOT NULL,
        -- 'requested' | 'cancelled' | 'exported' | 'reminder_sent' | 'hard_deleted'
    actor_user_id     UUID,
        -- auth.users.id si fue UI; NULL si fue cron.
    actor_email       TEXT,
        -- Snapshot del email del actor al momento del evento.
    actor_ip          INET,
    evidence          JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Detalles del evento: razón, confirmation_phrase usado, export_size_bytes, etc.
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tenant_offboarding_log_event_valid
        CHECK (event IN (
            'requested', 'cancelled', 'exported',
            'reminder_sent', 'hard_deleted', 'archived'
        ))
);

COMMENT ON TABLE public.tenant_offboarding_log IS
    'Append-only log de eventos del offboarding lifecycle. NO eliminar filas — '
    'sirve como evidencia forense post-hard-delete (retention 5y por Art. 22 Ley 1581). '
    'Sobrevive al borrado del tenant porque NO tiene FK CASCADE.';


CREATE INDEX IF NOT EXISTS tenant_offboarding_log_tenant_idx
    ON public.tenant_offboarding_log (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS tenant_offboarding_log_event_idx
    ON public.tenant_offboarding_log (event, occurred_at DESC);


-- 4. RLS — solo owner del tenant puede LEER su propio log; service_role full.
ALTER TABLE public.tenant_offboarding_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_offboarding_log_owner_select
    ON public.tenant_offboarding_log;
CREATE POLICY tenant_offboarding_log_owner_select
    ON public.tenant_offboarding_log
    FOR SELECT
    TO authenticated
    USING (
        tenant_id = ((auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
        AND EXISTS (
            SELECT 1 FROM public.tenant_users tu
             WHERE tu.tenant_id = tenant_offboarding_log.tenant_id
               AND tu.user_id   = auth.uid()
               AND tu.role      = 'owner'
        )
    );

-- NO POLICY para INSERT/UPDATE/DELETE — solo service_role escribe (vía API server).


-- 5. RPC helper para registrar eventos atómicamente (incluye fila tenant
-- update si aplica). Usado por services/api/lib/tenant_offboarding.py.
CREATE OR REPLACE FUNCTION public.fn_log_tenant_offboarding_event(
    p_tenant_id     UUID,
    p_event         TEXT,
    p_actor_user_id UUID DEFAULT NULL,
    p_actor_email   TEXT DEFAULT NULL,
    p_actor_ip      INET DEFAULT NULL,
    p_evidence      JSONB DEFAULT '{}'::jsonb
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    new_log_id BIGINT;
BEGIN
    INSERT INTO public.tenant_offboarding_log (
        tenant_id, event, actor_user_id, actor_email, actor_ip, evidence
    ) VALUES (
        p_tenant_id, p_event, p_actor_user_id, p_actor_email, p_actor_ip, p_evidence
    )
    RETURNING id INTO new_log_id;

    RETURN new_log_id;
END;
$$;

COMMENT ON FUNCTION public.fn_log_tenant_offboarding_event IS
    'Helper atómico para insertar evento de offboarding. SECURITY DEFINER porque '
    'el cron job y endpoints owner-only deben poder escribir sin estar bajo RLS '
    'authenticated.';

GRANT EXECUTE ON FUNCTION public.fn_log_tenant_offboarding_event TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_log_tenant_offboarding_event FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_log_tenant_offboarding_event FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_log_tenant_offboarding_event FROM anon;


-- 6. RPC que ejecuta soft-delete atómicamente. Es la única vía permitida desde
-- el backend; bloquea race conditions (e.g. doble click del owner).
CREATE OR REPLACE FUNCTION public.fn_request_tenant_deletion(
    p_tenant_id           UUID,
    p_actor_user_id       UUID,
    p_actor_email         TEXT,
    p_actor_ip            INET,
    p_reason              TEXT,
    p_grace_period_days   INTEGER DEFAULT 30
)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    scheduled_for TIMESTAMPTZ;
    existing      TIMESTAMPTZ;
BEGIN
    -- Bloqueo de fila para evitar race.
    SELECT deletion_requested_at INTO existing
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF existing IS NOT NULL THEN
        RAISE EXCEPTION
            'Tenant % ya tiene offboarding en curso desde %',
            p_tenant_id, existing
            USING ERRCODE = '40000'; -- transaction integrity
    END IF;

    scheduled_for := NOW() + (p_grace_period_days || ' days')::INTERVAL;

    UPDATE public.tenants
       SET deletion_requested_at  = NOW(),
           deletion_scheduled_for = scheduled_for,
           deletion_requested_by  = p_actor_user_id,
           deletion_reason        = p_reason
     WHERE id = p_tenant_id;

    -- Invalidar credenciales sensibles inmediatamente (NO esperar al hard-delete).
    -- Si el owner cancela, el flujo de re-credentialing lo manejará la UI.
    UPDATE public.tenant_integrations
       SET status = 'disconnected'
     WHERE tenant_id = p_tenant_id
       AND status   = 'connected';

    UPDATE public.tenant_payment_methods
       SET is_active = FALSE
     WHERE tenant_id = p_tenant_id
       AND is_active = TRUE;

    -- Log evento.
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'requested', p_actor_user_id, p_actor_email, p_actor_ip,
        jsonb_build_object(
            'reason', p_reason,
            'scheduled_for', scheduled_for,
            'grace_period_days', p_grace_period_days
        )
    );

    RETURN scheduled_for;
END;
$$;

COMMENT ON FUNCTION public.fn_request_tenant_deletion IS
    'Soft-delete del tenant + invalidación de credenciales sensibles + log evento. '
    'Atómico (FOR UPDATE row lock). Levanta SQLSTATE 40000 si ya hay offboarding '
    'en curso para evitar doble request.';

GRANT EXECUTE ON FUNCTION public.fn_request_tenant_deletion TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM anon;


-- 7. RPC cancel — revierte soft-delete dentro del grace period.
CREATE OR REPLACE FUNCTION public.fn_cancel_tenant_deletion(
    p_tenant_id     UUID,
    p_actor_user_id UUID,
    p_actor_email   TEXT,
    p_actor_ip      INET
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    was_in_progress BOOLEAN := FALSE;
    deleted         TIMESTAMPTZ;
BEGIN
    SELECT (deletion_requested_at IS NOT NULL), deleted_at
      INTO was_in_progress, deleted
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF NOT was_in_progress THEN
        RETURN FALSE;
    END IF;

    -- NO se puede cancelar si ya fue hard-deleted.
    IF deleted IS NOT NULL THEN
        RAISE EXCEPTION
            'Tenant % ya fue hard-deleted, no es cancelable',
            p_tenant_id
            USING ERRCODE = '40000';
    END IF;

    UPDATE public.tenants
       SET deletion_requested_at  = NULL,
           deletion_scheduled_for = NULL,
           deletion_requested_by  = NULL,
           deletion_reason        = NULL
     WHERE id = p_tenant_id;

    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'cancelled', p_actor_user_id, p_actor_email, p_actor_ip,
        jsonb_build_object('cancelled_at', NOW())
    );

    -- NOTA: las credenciales tenant_integrations + tenant_payment_methods
    -- quedan disconnected/inactive. El owner debe re-conectarlas vía UI
    -- normal (consciente decision para evitar replay attack: si el secret
    -- ya estuvo "out" durante el grace period, mejor rotar).
    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION public.fn_cancel_tenant_deletion IS
    'Revierte soft-delete dentro del grace period. NO restaura credenciales '
    '(consciente: forzar re-connect mitiga replay si el secret estuvo "out").';

GRANT EXECUTE ON FUNCTION public.fn_cancel_tenant_deletion TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_cancel_tenant_deletion FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_cancel_tenant_deletion FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_cancel_tenant_deletion FROM anon;
