-- F0 (roadmap producción 2026-07-02) — endurecimiento RLS: añadir WITH CHECK a las 30 policies FOR ALL
-- que solo tenían USING. Sin WITH CHECK, un cliente autenticado podría INSERT/UPDATE una fila con
-- tenant_id de OTRO tenant (el USING solo filtra lecturas/qué filas afecta un UPDATE, no valida la fila nueva).
--
-- SEGURO: ALTER POLICY ... WITH CHECK solo AÑADE la validación de escritura; NO toca el USING → los reads
-- no cambian. WITH CHECK = espejo del USING (una fila solo se puede escribir si cumple la misma condición de
-- tenant bajo la que se puede leer). Guardado por existencia (re-ejecutable). service_role bypasa RLS (sin efecto).
-- Fuente: pg_policies (with_check IS NULL AND cmd='ALL'), verificado 2026-07-02.

DO $$
DECLARE r record;
BEGIN
  FOR r IN (
    SELECT * FROM (VALUES
      ('api_security_events','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('audit_log','tenant_isolation_audit_log','(tenant_id = app_current_tenant())'),
      ('contacts','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('conversations','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('expenses','Tenants can manage their expenses','(tenant_id = app_current_tenant())'),
      ('idempotency_keys','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('integration_oauth_states','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('kb_documents','tenant_isolation_kb_documents','(tenant_id = app_current_tenant())'),
      ('messages','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('notification_settings','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('order_items','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('order_tracking','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('orders','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('product_variations','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('products','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('purchase_order_items','Tenants can manage their PO items','(tenant_id = app_current_tenant())'),
      ('purchase_orders','Tenants can manage their POs','(tenant_id = app_current_tenant())'),
      ('shipments','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('stock_movements','tenant_isolation_stock_movements','(tenant_id = app_current_tenant())'),
      ('suppliers','Tenants can manage their suppliers','(tenant_id = app_current_tenant())'),
      ('tenant_integrations','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('tenant_shipping_provider_config','tspc_modify_own_tenant','(tenant_id = app_current_tenant())'),
      ('tenant_subscriptions','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('tenant_usage_counters','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('tenant_usage_events','Tenant Isolation','(tenant_id = app_current_tenant())'),
      ('tenant_users','Tenant Isolation — tenant_users','(tenant_id = app_current_tenant())'),
      ('tenants','Tenant Isolation','(id = app_current_tenant())'),
      ('platform_categories','Platform categories are read-only for tenants','(false)'),
      ('ai_agents','Tenants can manage their own AI agent','(tenant_id IN ( SELECT tu.tenant_id FROM tenant_users tu WHERE (tu.user_id = auth.uid())))'),
      ('marketplace_listings','tenant_isolation_marketplace','(tenant_id = ( SELECT (((auth.jwt() -> ''app_metadata''::text) ->> ''tenant_id''::text))::uuid))')
    ) AS v(tbl, pol, chk)
  ) LOOP
    IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=r.tbl AND policyname=r.pol) THEN
      EXECUTE format('ALTER POLICY %I ON public.%I WITH CHECK (%s)', r.pol, r.tbl, r.chk);
    ELSE
      RAISE NOTICE 'F0 WITH CHECK: policy "%" on "%" no existe — skip', r.pol, r.tbl;
    END IF;
  END LOOP;
END $$;
