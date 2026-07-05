-- =============================================================================
-- F6 — Fix flujos rotos por DB: cierre de cuenta + guardar métodos de pago.
-- Fecha: 2026-07-04  ·  Banda de timestamp F6/F7 asignada.
--
-- Dos bugs confirmados que dejan features 100% caídas:
--
--   (1) BUG_REAL 42703 — fn_request_tenant_deletion (migración
--       20260616000000:197-200) ejecuta:
--           UPDATE public.tenant_payment_methods SET is_active = FALSE ...
--       pero la tabla (20260603000000) SOLO define la columna `enabled`.
--       En runtime PostgreSQL levanta ERROR 42703 (undefined_column) →
--       toda la transacción de la RPC aborta → el cierre de cuenta NUNCA
--       completa. Aquí re-creamos la función con la columna correcta.
--
--   (2) RLS write service_role-only en tenant_payment_methods bloquea el
--       toggle desde la server action de sesión del owner
--       (savePaymentMethods usa el cliente supabase de sesión, no
--       service_role). Añadimos una write-policy scoped por tenant + rol
--       owner para que el panel de Pagos persista. La policy service_role
--       existente se conserva (path API), las policies se OR-ean.
--
-- Idempotente: CREATE OR REPLACE + DROP POLICY IF EXISTS. NO aplicar aún.
-- =============================================================================

-- ─── (1) Fix columna is_active → enabled en fn_request_tenant_deletion ────────
-- Reproducción EXACTA del cuerpo original (20260616000000) cambiando solo el
-- UPDATE de tenant_payment_methods. Mantiene firma, GRANT/REVOKE y semántica.

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

    -- FIX F6: la columna canónica es `enabled` (NO is_active). El typo original
    -- abortaba la RPC con 42703 y el cierre de cuenta nunca completaba.
    UPDATE public.tenant_payment_methods
       SET enabled = FALSE
     WHERE tenant_id = p_tenant_id
       AND enabled = TRUE;

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
    'en curso. F6 2026-07-04: fix columna enabled (era is_active → 42703).';

GRANT EXECUTE ON FUNCTION public.fn_request_tenant_deletion TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_request_tenant_deletion FROM anon;


-- ─── (2) Write-policy owner scoped-por-tenant en tenant_payment_methods ───────
-- La policy service_role-only ("tenant_payment_methods_write_service") se
-- conserva (path API auditado). Esta policy adicional permite al OWNER escribir
-- desde su sesión JWT (savePaymentMethods). RLS OR-ea policies permisivas.
-- El gate de app ya restringe a owner (getOwnerTenantId); esto lo refleja en DB.

DROP POLICY IF EXISTS "tenant_payment_methods_write_owner"
    ON public.tenant_payment_methods;
CREATE POLICY "tenant_payment_methods_write_owner"
    ON public.tenant_payment_methods
    FOR ALL
    TO authenticated
    USING (
        tenant_id = ((auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    )
    WITH CHECK (
        tenant_id = ((auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- Force PostgREST schema cache reload.
NOTIFY pgrst, 'reload schema';
