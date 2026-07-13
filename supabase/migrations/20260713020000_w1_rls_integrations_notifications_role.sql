-- ============================================================
-- W1 (auditoría 2026-07-13) — RLS role-blind en tenant_integrations + notification_settings
-- ============================================================
-- Ambas tenían `FOR ALL USING (tenant_id = app_current_tenant())` (fase9_schema_core,
-- 2026-04-09) SIN check de rol → cualquier miembro autenticado (incl. OPERATOR) podía
-- reescribir la config de integración (phone_number_id, waba, status, meta) o el
-- notification_settings (chat_id Telegram) vía PostgREST directo, saltándose el gate
-- owner/manager de la página de integraciones (que redirige a operators).
--
-- FIX (idioma f6/tenant_users): SELECT para miembros (lectura de estado de integración
-- — los secrets ya están protegidos por el role-check de los pgsec_* RPCs) + escrituras
-- owner/manager (coincide con la página integrations: canWrite = owner||manager).
-- service_role (backend bot/connector) bypasa RLS → intacto.

-- ── tenant_integrations ───────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenant_integrations;
DROP POLICY IF EXISTS tenant_integrations_select_member ON public.tenant_integrations;
CREATE POLICY tenant_integrations_select_member
    ON public.tenant_integrations
    FOR SELECT
    USING (tenant_id = app_current_tenant());

DROP POLICY IF EXISTS tenant_integrations_write_privileged ON public.tenant_integrations;
CREATE POLICY tenant_integrations_write_privileged
    ON public.tenant_integrations
    FOR ALL
    USING (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    )
    WITH CHECK (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- ── notification_settings ─────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenant Isolation" ON public.notification_settings;
DROP POLICY IF EXISTS notification_settings_select_member ON public.notification_settings;
CREATE POLICY notification_settings_select_member
    ON public.notification_settings
    FOR SELECT
    USING (tenant_id = app_current_tenant());

DROP POLICY IF EXISTS notification_settings_write_privileged ON public.notification_settings;
CREATE POLICY notification_settings_write_privileged
    ON public.notification_settings
    FOR ALL
    USING (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    )
    WITH CHECK (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
    );

-- Nota: la policy FOR ALL de escritura también cubre SELECT para owner/manager, pero
-- la policy FOR SELECT de miembros (permissive OR) garantiza que un operator siga
-- LEYENDO el estado de integración (p.ej. Inbox checando si WhatsApp está conectado)
-- sin poder ESCRIBIR. Los secrets NO se exponen (pgsec_* RPC role-gated, W1).
COMMENT ON POLICY tenant_integrations_write_privileged ON public.tenant_integrations IS
    'W1 2026-07-13: escrituras owner/manager (USING+WITH CHECK). Cierra reescritura de config por operator vía PostgREST directo.';
