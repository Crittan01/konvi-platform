-- Rev. 107 fix RLS — usar app_current_tenant() en vez de current_setting() directo.
--
-- Reportado por founder UAT 2026-05-22: el módulo Cotizador
-- /dashboard/shipping mostraba "provider activo es envia" aun cuando DB
-- tenía active_provider='aveonline'. Causa: las policies RLS de
-- tenant_shipping_provider_config usaban `current_setting('app.current_tenant_id', true)::uuid`
-- directamente. Ese GUC NO está seteado en Next.js server components
-- (que usan createClient() con cookie auth-user). Resultado: policy retornaba
-- FALSE → 0 rows → page.tsx hacía fallback a 'envia'.
--
-- Patrón canónico del repo (`app_current_tenant()` en migración
-- 20260406181238_rls_policies.sql) hace COALESCE entre el GUC y el claim
-- JWT del usuario authenticated:
--
--   SELECT COALESCE(
--     NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
--     (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
--   );
--
-- Eso permite que server components con cookie-auth funcionen, igual que
-- workers con el GUC seteado.

DROP POLICY IF EXISTS tspc_select_own_tenant
    ON public.tenant_shipping_provider_config;
DROP POLICY IF EXISTS tspc_modify_own_tenant
    ON public.tenant_shipping_provider_config;

CREATE POLICY tspc_select_own_tenant
    ON public.tenant_shipping_provider_config
    FOR SELECT
    USING (tenant_id = app_current_tenant());

CREATE POLICY tspc_modify_own_tenant
    ON public.tenant_shipping_provider_config
    FOR ALL
    USING (tenant_id = app_current_tenant());

COMMENT ON POLICY tspc_select_own_tenant ON public.tenant_shipping_provider_config IS
    'Tenant isolation usando app_current_tenant() — soporta workers (GUC) '
    'Y server components Next.js (JWT claim).';
