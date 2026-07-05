-- =============================================================================
-- F6 — Endurecer RLS con check de rol: tenants + tenant_provider_health.
-- Fecha: 2026-07-04
--
-- Brecha real y determinística (principio 2: el frontend NO es seguridad):
--
--   (1) public.tenants — policy "Tenant Isolation" es FOR ALL USING
--       (id = app_current_tenant()) → CUALQUIER miembro del tenant
--       (operator/viewer) con JWT válido puede UPDATE tenants vía
--       supabase-js/PostgREST, saltándose el gate owner de la app.
--       Separamos: SELECT para cualquier miembro · UPDATE solo owner/manager.
--       INSERT/DELETE de tenants NO se exponen a sesión (provisioning y
--       offboarding usan RPC SECURITY DEFINER / service_role, que además
--       bypassa RLS).
--
--   (2) public.tenant_provider_health — SELECT permitía a cualquier
--       authenticated del tenant leer la columna JSONB `detail` (webhook_info
--       de Telegram, raw Graph API de WhatsApp, cuerpos de error crudos).
--       La página Salud ya está gated a owner/manager; restringimos la policy
--       para que coincida y un operator no pueda exfiltrar `detail` vía
--       PostgREST.
--
-- service_role (cron/API) bypassa RLS → NO afectado. Idempotente.
-- =============================================================================

-- ─── (1) tenants: SELECT miembro · UPDATE owner/manager ───────────────────────

DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenants;

-- Lectura: cualquier miembro del tenant (mismo alcance que antes).
DROP POLICY IF EXISTS tenants_select_member ON public.tenants;
CREATE POLICY tenants_select_member
    ON public.tenants
    FOR SELECT
    USING (id = app_current_tenant());

-- Escritura: solo owner/manager del tenant. El claim de rol vive en
-- app_metadata.role (poblado por Supabase Auth en el JWT de sesión).
DROP POLICY IF EXISTS tenants_update_privileged ON public.tenants;
CREATE POLICY tenants_update_privileged
    ON public.tenants
    FOR UPDATE
    USING (
        id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    )
    WITH CHECK (
        id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );


-- ─── (2) tenant_provider_health: SELECT owner/manager ─────────────────────────

DROP POLICY IF EXISTS tenant_provider_health_tenant_select
    ON public.tenant_provider_health;
CREATE POLICY tenant_provider_health_tenant_select
    ON public.tenant_provider_health
    FOR SELECT
    TO authenticated
    USING (
        tenant_id = ((auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- Force PostgREST schema cache reload.
NOTIFY pgrst, 'reload schema';
