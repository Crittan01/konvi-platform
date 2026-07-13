-- ============================================================
-- OLA 0 (auditoría 2026-07-13) — CRITICAL: escalada RBAC operator/manager -> owner
-- ============================================================
-- La policy "Tenant Isolation — tenant_users" (20260415000000) era:
--     FOR ALL USING (tenant_id = app_current_tenant())
-- SIN check de rol ni WITH CHECK. Cualquier miembro autenticado (operator/manager)
-- podía, con su propia sesión vía PostgREST:
--     UPDATE tenant_users SET role='owner' WHERE user_id=<self>   -- USING pasa (su tenant)
-- y el custom_access_token_hook (20260426070000) inyectaba el rol elevado en el JWT
-- al siguiente refresh -> escalada a owner con 1 request (borrado de cuenta,
-- export PII/SAR, rotación de credenciales, refunds).
--
-- FIX (idioma f6 20260704156010): SELECT para miembros + escrituras OWNER-ONLY,
-- con USING **y** WITH CHECK. Coincide con el modelo real de la app: la página
-- de equipo es owner-only (redirect si no owner) y todas las mutaciones corren
-- desde sesiones owner. Los RPCs de provisioning/invite (add_member_to_tenant,
-- provision_tenant) son SECURITY DEFINER -> bypassean RLS -> siguen funcionando.
-- El hook (SECURITY DEFINER) sigue leyendo tenant_users sin problema.

DROP POLICY IF EXISTS "Tenant Isolation — tenant_users" ON public.tenant_users;

-- Lectura: cualquier miembro del tenant ve a su equipo (mismo alcance que antes).
DROP POLICY IF EXISTS tenant_users_select_member ON public.tenant_users;
CREATE POLICY tenant_users_select_member
    ON public.tenant_users
    FOR SELECT
    USING (tenant_id = app_current_tenant());

-- Alta de miembro: solo owner (defensa en profundidad; el alta canónica es vía
-- el RPC SECURITY DEFINER add_member_to_tenant, que valida rol).
DROP POLICY IF EXISTS tenant_users_insert_owner ON public.tenant_users;
CREATE POLICY tenant_users_insert_owner
    ON public.tenant_users
    FOR INSERT
    WITH CHECK (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- Cambio de miembro (rol/status): solo owner. Cierra la escalada — un operator
-- o manager NO puede UPDATE su propia fila (su claim de rol no es 'owner').
DROP POLICY IF EXISTS tenant_users_update_owner ON public.tenant_users;
CREATE POLICY tenant_users_update_owner
    ON public.tenant_users
    FOR UPDATE
    USING (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    )
    WITH CHECK (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- Baja de miembro: solo owner.
DROP POLICY IF EXISTS tenant_users_delete_owner ON public.tenant_users;
CREATE POLICY tenant_users_delete_owner
    ON public.tenant_users
    FOR DELETE
    USING (
        tenant_id = app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

COMMENT ON POLICY tenant_users_update_owner ON public.tenant_users IS
    'OLA0 2026-07-13: escrituras owner-only (USING+WITH CHECK). Cierra escalada operator/manager->owner por UPDATE directo vía PostgREST (auditoría CRITICAL).';
