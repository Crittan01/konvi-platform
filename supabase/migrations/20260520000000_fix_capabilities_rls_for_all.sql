-- =============================================================================
-- Fix RLS tenant_provider_capabilities — permitir INSERT/UPDATE/DELETE
-- desde sesión authenticated user con tenant scope (rev. 105 2026-05-07).
--
-- Disparador: founder reportó error desde UI al togglear capability:
--   "new row violates row-level security policy for table
--    tenant_provider_capabilities"
--
-- Causa raíz: la migration original (20260514140000) creó solo policy
-- FOR SELECT, asumiendo que INSERT/UPDATE solo vendrían vía service_role
-- (comentario explícito en migration). Pero los server actions Next.js
-- usan JWT user (no service_role) — el patrón actual del Tenant Console
-- → RLS bloquea las operaciones legítimas del owner.
--
-- Tabla `tenant_carriers` (migration 20260517) NO tiene este bug porque
-- usó policy FOR ALL desde el inicio. Tenant_provider_capabilities
-- adopta el mismo pattern.
--
-- VERIFICACIÓN DE SEGURIDAD: policy FOR ALL con tenant scope mantiene
-- la garantía de aislamiento — tenant A NO puede insertar/leer/escribir
-- rows de tenant B. Cambio es ADITIVO en términos de funcionalidad
-- (permite más operaciones legítimas), NO laxo en seguridad.
-- =============================================================================

-- Drop policy existente solo-SELECT.
DROP POLICY IF EXISTS tenant_provider_capabilities_tenant_select
    ON public.tenant_provider_capabilities;

-- Crear policy FOR ALL con tenant scope, usando la función canónica
-- `public.app_current_tenant()` (consistente con tenant_carriers, coupons,
-- contacts, etc.).
DROP POLICY IF EXISTS tenant_provider_capabilities_tenant_iud
    ON public.tenant_provider_capabilities;
CREATE POLICY tenant_provider_capabilities_tenant_iud
    ON public.tenant_provider_capabilities
    FOR ALL
    USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

-- Comentario de mantenimiento.
COMMENT ON POLICY tenant_provider_capabilities_tenant_iud
    ON public.tenant_provider_capabilities IS
    'Tenant Isolation FOR ALL. Reemplaza policy original FOR SELECT '
    '(2026-05-14) que bloqueaba server actions Next.js. Aislamiento '
    'garantizado por tenant_id = app_current_tenant() in USING+WITH CHECK.';
