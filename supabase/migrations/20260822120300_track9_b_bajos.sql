-- =============================================================================
-- Track 9 / Tier BAJO — rol fresco (no claim JWT), WITH CHECK faltantes, search_path
-- en SECDEF, overloads legacy, grants peligrosos residuales y CAUSA RAÍZ de la ola.
-- Fecha: 2026-08-22 · Origen: PLAN-CIERRE §Track 9 · Tests: tests/dbharness/test_track9_b_bajos.py
--
-- B-a: 12 policies leían el rol del claim JWT (app_metadata.role). Ese claim vive lo
--   que viva el JWT: un owner degradado a operator seguía actuando como owner hasta la
--   expiración del token (verificado con exploit: INSERT en tenant_users autorizado por
--   un JWT stale). Todas pasan a app_current_role() — rol FRESCO de tenant_users, que
--   además exige status='active' (coherente con A9).
-- B-h + CAUSA RAÍZ: los defaults de Supabase otorgan ALL (incl. TRUNCATE/REFERENCES/
--   TRIGGER) a anon+authenticated en TODA tabla, y EXECUTE a authenticated en TODA
--   función nueva (así nació expuesta upsert_aveonline_idagente el mismo 2026-08-22).
--   Se revocan en lo existente y en los DEFAULT PRIVILEGES: lo nuevo nace cerrado y
--   cada migración futura otorga GRANT explícito (el guard CI de Track 9 lo exige).
-- =============================================================================

-- ── B-a: policies con rol del JWT → app_current_role() ───────────────────────────────

DROP POLICY IF EXISTS "Owners can read their expenses" ON public.expenses;
CREATE POLICY "Owners can read their expenses" ON public.expenses
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS "Owners can read their PO items" ON public.purchase_order_items;
CREATE POLICY "Owners can read their PO items" ON public.purchase_order_items
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS "Owners can read their POs" ON public.purchase_orders;
CREATE POLICY "Owners can read their POs" ON public.purchase_orders
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS "Owners can read their suppliers" ON public.suppliers;
CREATE POLICY "Owners can read their suppliers" ON public.suppliers
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS notification_settings_write_privileged ON public.notification_settings;
CREATE POLICY notification_settings_write_privileged ON public.notification_settings
  FOR ALL TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (tenant_id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'));

DROP POLICY IF EXISTS tenant_integrations_write_privileged ON public.tenant_integrations;
CREATE POLICY tenant_integrations_write_privileged ON public.tenant_integrations
  FOR ALL TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (tenant_id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'));

DROP POLICY IF EXISTS tenant_payment_methods_write_owner ON public.tenant_payment_methods;
CREATE POLICY tenant_payment_methods_write_owner ON public.tenant_payment_methods
  FOR ALL TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner')
  WITH CHECK (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS tenant_users_insert_owner ON public.tenant_users;
CREATE POLICY tenant_users_insert_owner ON public.tenant_users
  FOR INSERT TO authenticated
  WITH CHECK (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS tenant_users_update_owner ON public.tenant_users;
CREATE POLICY tenant_users_update_owner ON public.tenant_users
  FOR UPDATE TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner')
  WITH CHECK (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS tenant_users_delete_owner ON public.tenant_users;
CREATE POLICY tenant_users_delete_owner ON public.tenant_users
  FOR DELETE TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

DROP POLICY IF EXISTS tenants_update_privileged ON public.tenants;
CREATE POLICY tenants_update_privileged ON public.tenants
  FOR UPDATE TO authenticated
  USING (id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'));

DROP POLICY IF EXISTS tenant_provider_health_tenant_select ON public.tenant_provider_health;
CREATE POLICY tenant_provider_health_tenant_select ON public.tenant_provider_health
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() IN ('owner', 'manager'));

-- ── B-c: user_dismissed_alerts — UPDATE sin WITH CHECK (la alerta podía reasignarse a
--        otro usuario/tenant). Recreadas con WITH CHECK y tenant vía helper (no claim).
DROP POLICY IF EXISTS "user reads own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user reads own dismissed alerts" ON public.user_dismissed_alerts
  FOR SELECT TO authenticated
  USING (user_id = auth.uid() AND tenant_id = public.app_current_tenant());

DROP POLICY IF EXISTS "user updates own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user updates own dismissed alerts" ON public.user_dismissed_alerts
  FOR UPDATE TO authenticated
  USING (user_id = auth.uid() AND tenant_id = public.app_current_tenant())
  WITH CHECK (user_id = auth.uid() AND tenant_id = public.app_current_tenant());

DROP POLICY IF EXISTS "user upserts own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user upserts own dismissed alerts" ON public.user_dismissed_alerts
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid() AND tenant_id = public.app_current_tenant());

-- ── B-d: bot_source_log — log del bot mutable por clientes. La consola no lo lee
--        (grep apps/web: 0 callers) → service_role-only. La policy de tenant queda
--        inerte sin privilegio de tabla; se dropea para no dejar fachada.
DROP POLICY IF EXISTS bot_source_log_tenant_isolation ON public.bot_source_log;
REVOKE ALL ON public.bot_source_log FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bot_source_log TO service_role;

-- ── B-e: SECDEF sin SET search_path (secuestro de search_path con privilegios del
--        owner). El plan citaba 9; el conteo real verificado en DB live es 4.
ALTER FUNCTION public.cleanup_expired_rate_limit_windows(integer) SET search_path = public, pg_catalog;
ALTER FUNCTION public.outbound_idempotency_lookup(text, uuid, text) SET search_path = public, pg_catalog;
ALTER FUNCTION public.outbound_idempotency_register(text, uuid, text, integer, jsonb, jsonb, integer) SET search_path = public, pg_catalog;
ALTER FUNCTION public.outbound_idempotency_cleanup() SET search_path = public, pg_catalog;

-- ── B-f: mfa_recovery_codes — todo el flujo MFA usa service_role (routers/mfa.py con
--        get_service_client, verificado 2026-08-22). Las policies owner_select/delete
--        eran fachada sobre hashes bcrypt que el usuario nunca debe leer por PostgREST.
DROP POLICY IF EXISTS mfa_recovery_codes_owner_select ON public.mfa_recovery_codes;
DROP POLICY IF EXISTS mfa_recovery_codes_owner_delete ON public.mfa_recovery_codes;
REVOKE ALL ON public.mfa_recovery_codes FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.mfa_recovery_codes TO service_role;

-- ── B-g: overloads legacy — el código usa las firmas con p_tenant_id / p_model_version
--        (stock_reservation.py, kb_tool.py, ai_preview.py — verificado por grep).
DROP FUNCTION public.rpc_stock_reservation_release(uuid);
DROP FUNCTION public.rpc_stock_reservation_extend(uuid, integer);
DROP FUNCTION public.rpc_stock_reservation_consume(uuid, uuid);
DROP FUNCTION public.match_kb_documents(vector, double precision, integer, uuid);

-- ── B-h: grants peligrosos residuales — TRUNCATE/REFERENCES/TRIGGER para roles de
--        cliente en TODAS las tablas y vistas de public. TRUNCATE no pasa por RLS:
--        PostgREST no expone esos comandos, pero el privilegio no debe existir.
DO $$
DECLARE
  v_obj TEXT;
BEGIN
  FOR v_obj IN
    SELECT format('%I', t.tablename) FROM pg_tables t WHERE t.schemaname = 'public'
    UNION ALL
    SELECT format('%I', v.viewname) FROM pg_views v WHERE v.schemaname = 'public'
  LOOP
    EXECUTE format('REVOKE TRUNCATE, REFERENCES, TRIGGER ON public.%s FROM anon, authenticated', v_obj);
  END LOOP;
END $$;

-- ── CAUSA RAÍZ (funciones): dos vías de exposición al crear una función nueva:
--    (a) el default ACL de Supabase otorgaba EXECUTE explícito a anon/authenticated
--        (así se expuso upsert_aveonline_idagente el mismo día de su migración);
--    (b) el built-in de Postgres: TODA función nace con EXECUTE para PUBLIC, y se
--        demostró empíricamente (PG 17.6, DB limpia de prueba) que ALTER DEFAULT
--        PRIVILEGES NO puede quitar ese built-in: proacl NULL = defaults nativos.
--    Cobertura en capas:
--      1. default ACL sin grants de cliente (los REVOKEs de abajo);
--      2. event trigger que revoca PUBLIC automáticamente en cada CREATE FUNCTION del
--         schema public (el mismo mecanismo que Supabase usa con sus issue_*_access);
--      3. guard CI (Track 9) que exige REVOKE explícito + search_path en la migración;
--      4. barrido vivo en dbharness (ninguna SECDEF ejecutable por PUBLIC/anon).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM authenticated;

CREATE OR REPLACE FUNCTION public.track9_revoke_public_on_new_function()
 RETURNS event_trigger
 LANGUAGE plpgsql
 SET search_path = public, pg_catalog
AS $function$
DECLARE
  v_cmd RECORD;
BEGIN
  -- Solo funciones del schema public creadas a partir de esta migración. CREATE OR
  -- REPLACE preserva los ACL existentes y vuelve a disparar el tag: el REVOKE de
  -- PUBLIC es idempotente y es exactamente la propiedad que se quiere mantener.
  FOR v_cmd IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
    IF v_cmd.schema_name = 'public' AND v_cmd.object_type = 'function' THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', v_cmd.object_identity);
    END IF;
  END LOOP;
END;
$function$;

DROP EVENT TRIGGER IF EXISTS track9_revoke_public_on_new_function;
CREATE EVENT TRIGGER track9_revoke_public_on_new_function
  ON ddl_command_end WHEN TAG IN ('CREATE FUNCTION')
  EXECUTE FUNCTION public.track9_revoke_public_on_new_function();

-- ── B-a (storage): las policies de escritura del bucket tenant-media también leían el
--    rol del claim JWT → rol fresco vía app_current_role() (mismo alcance: owner/manager
--    del tenant de la carpeta).
DROP POLICY IF EXISTS tenant_media_write_privileged ON storage.objects;
CREATE POLICY tenant_media_write_privileged ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'tenant-media'
    AND (storage.foldername(name))[1] = (public.app_current_tenant())::text
    AND public.app_current_role() IN ('owner', 'manager'));

DROP POLICY IF EXISTS tenant_media_update_privileged ON storage.objects;
CREATE POLICY tenant_media_update_privileged ON storage.objects
  FOR UPDATE TO authenticated
  USING (bucket_id = 'tenant-media'
    AND (storage.foldername(name))[1] = (public.app_current_tenant())::text
    AND public.app_current_role() IN ('owner', 'manager'));

DROP POLICY IF EXISTS tenant_media_delete_privileged ON storage.objects;
CREATE POLICY tenant_media_delete_privileged ON storage.objects
  FOR DELETE TO authenticated
  USING (bucket_id = 'tenant-media'
    AND (storage.foldername(name))[1] = (public.app_current_tenant())::text
    AND public.app_current_role() IN ('owner', 'manager'));

-- ── CAUSA RAÍZ (tablas futuras): sin TRUNCATE/REFERENCES/TRIGGER heredados tampoco.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLES FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLES FROM authenticated;
