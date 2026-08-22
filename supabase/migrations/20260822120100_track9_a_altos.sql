-- =============================================================================
-- Track 9 / Tier ALTO (A1-A9) — RPCs admin cross-tenant, RESTRICTIVE de dinero,
-- miembros 'inactive' con acceso persistente
-- Fecha: 2026-08-22 · Origen: PLAN-CIERRE §Track 9 · Tests: tests/dbharness/test_track9_a_altos.py
-- (los 22 ataques ejecutaban antes de este fix; evidencia en bitácora PLAN.md §E)
--
-- A1-A4 + extras: REVOKE de RPCs administrativas a service_role (todos los callers
--   reales verificados por grep: meli_client, aveonline_client, aveonline_webhook,
--   plans.py, settings.py, reversion_pago — service_role; apps/web no llama ninguna).
-- A5-A8: policies RESTRICTIVE (overlay — las permisivas de tenant quedan intactas;
--   el patrón W2b 20260725040000: nunca tocar SELECT salvo A7, y jamás service_role,
--   que bypasa RLS — la mutación legítima va por la API).
-- A9: todo gate basado en tenant_users debe exigir status='active'. El status vive
--   en tenant_users y Supabase Auth no lo conoce: el refresh token sigue emitiendo
--   JWTs y auth.uid() resuelve para siempre → sin el filtro, un miembro desactivado
--   conserva acceso INDEFINIDO a secretos/credenciales/tablas gated por membresía.
-- =============================================================================

-- ── A1: lease de refresh de tokens MeLi (robo de lease / marcar integración ajena en error)
REVOKE ALL ON FUNCTION public.rpc_meli_try_refresh_lease(uuid, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rpc_meli_release_refresh_lease(uuid, uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rpc_meli_note_refresh_failure(uuid, uuid, text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_meli_try_refresh_lease(uuid, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.rpc_meli_release_refresh_lease(uuid, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rpc_meli_note_refresh_failure(uuid, uuid, text, integer) TO service_role;

-- ── A2: credenciales del carrier Aveonline (escritura cross-tenant del JWT cacheado)
REVOKE ALL ON FUNCTION public.upsert_aveonline_jwt(uuid, text, timestamp with time zone) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_aveonline_jwt(uuid, text, timestamp with time zone) TO service_role;

-- ── A3: eventos de tracking de envíos (falsificación de estados / forenses falsos;
--        los webhooks de Aveonline entran con service_role)
REVOKE ALL ON FUNCTION public.fn_record_shipment_tracking_event(uuid, uuid, uuid, text, text, text, integer, text, text, timestamp with time zone, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_record_shipment_tracking_event(uuid, uuid, uuid, text, text, text, integer, text, text, timestamp with time zone, jsonb) TO service_role;

-- ── A4: consumo de cuotas por plan (DoS de cuotas cross-tenant)
REVOKE ALL ON FUNCTION public.consume_tenant_capability(uuid, text, integer, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_tenant_capability(uuid, text, integer, jsonb) TO service_role;

-- ── Extra 1: get_tenant_plan_capabilities no tiene guarda de tenant (lectura cross-tenant
--    del plan de cualquier tenant). Único caller: settings.py con service_role.
REVOKE ALL ON FUNCTION public.get_tenant_plan_capabilities(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_tenant_plan_capabilities(uuid) TO service_role;

-- ── Extra 2: reversion_procede como oráculo cross-tenant (payment_method + existencia
--    de pedidos ajenos). Único caller: reversion_pago.py con service_role.
REVOKE ALL ON FUNCTION public.reversion_procede(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reversion_procede(uuid, uuid) TO service_role;

-- ── A5: claims — la gestión de reclamos toca la plata del cliente (reversos/reembolsos).
--    UPDATE solo owner/manager (rol FRESCO vía app_current_role); DELETE de nadie por PostgREST.
DROP POLICY IF EXISTS track9_claims_update_privileged ON public.claims;
CREATE POLICY track9_claims_update_privileged ON public.claims AS RESTRICTIVE
  FOR UPDATE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_claims_no_delete ON public.claims;
CREATE POLICY track9_claims_no_delete ON public.claims AS RESTRICTIVE
  FOR DELETE TO authenticated USING (false);

-- ── A6: order_cancellations — "append-only" declarado (G-7) pero mutable por PostgREST.
DROP POLICY IF EXISTS track9_cancellations_no_update ON public.order_cancellations;
CREATE POLICY track9_cancellations_no_update ON public.order_cancellations AS RESTRICTIVE
  FOR UPDATE TO authenticated USING (false);
DROP POLICY IF EXISTS track9_cancellations_no_delete ON public.order_cancellations;
CREATE POLICY track9_cancellations_no_delete ON public.order_cancellations AS RESTRICTIVE
  FOR DELETE TO authenticated USING (false);

-- ── A7: payments — lectura financiera owner-only (matriz de la consola: Finanzas es
--    owner, guard server-side en finance/page.tsx). La página de pedido (orders/[id],
--    cualquier miembro) pasa a leer la VISTA proyectada payments_safe: sin raw_webhook
--    (PII del pagador) ni wompi_txn_id. La vista es del owner postgres (bypasa RLS de la
--    tabla) — la barrera es su WHERE tenant_id = app_current_tenant() + security_barrier.
DROP POLICY IF EXISTS track9_payments_select_owner ON public.payments;
CREATE POLICY track9_payments_select_owner ON public.payments AS RESTRICTIVE
  FOR SELECT TO authenticated
  USING (public.app_current_role() = 'owner');

CREATE OR REPLACE VIEW public.payments_safe
WITH (security_barrier = true) AS
SELECT id, tenant_id, order_id, provider, checkout_url, amount_in_cents, currency,
       status, wompi_status, created_at, updated_at
FROM public.payments
WHERE tenant_id = public.app_current_tenant();

REVOKE ALL ON public.payments_safe FROM PUBLIC, anon;
GRANT SELECT ON public.payments_safe TO authenticated;

-- ── A8: api_security_events — log forense append-only (ni insert/update/delete por
--    PostgREST; la escritura real es del API con service_role).
DROP POLICY IF EXISTS track9_asec_no_insert ON public.api_security_events;
CREATE POLICY track9_asec_no_insert ON public.api_security_events AS RESTRICTIVE
  FOR INSERT TO authenticated WITH CHECK (false);
DROP POLICY IF EXISTS track9_asec_no_update ON public.api_security_events;
CREATE POLICY track9_asec_no_update ON public.api_security_events AS RESTRICTIVE
  FOR UPDATE TO authenticated USING (false);
DROP POLICY IF EXISTS track9_asec_no_delete ON public.api_security_events;
CREATE POLICY track9_asec_no_delete ON public.api_security_events AS RESTRICTIVE
  FOR DELETE TO authenticated USING (false);

-- ── A9 (funciones): guardas de Vault/credenciales con status='active' ────────────────
-- Cuerpos idénticos a los vigentes salvo el filtro de status en tenant_users.
-- (pgsec_* siguen ejecutables por authenticated: la consola de integraciones las usa
--  — el candado es la guarda interna owner/manager+active, no el ACL.)
--
-- Exenciones del guard CI (scripts/check_secdef_grants.py) — RPCs de consola:
-- track9:exempt:pgsec_create_secret — consola (integrations page) la invoca con authenticated; candado = guarda interna owner/manager+active.
-- track9:exempt:pgsec_read_secret — idem; fail-closed a anon (RETURN NULL) + guarda interna.
-- track9:exempt:pgsec_update_secret — idem pgsec_create_secret.
-- track9:exempt:pgsec_delete_secret — idem pgsec_create_secret.
-- track9:exempt:pgsec_upsert_secret — idem pgsec_create_secret.
-- track9:exempt:get_aveonline_credentials — consola (shipping settings) la invoca con authenticated; candado = guarda interna owner/manager+active (M14).

CREATE OR REPLACE FUNCTION public.pgsec_create_secret(p_secret text, p_name text, p_description text DEFAULT ''::text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_owner uuid;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: status='active' — un miembro desactivado NO puede crear secretos
        -- (su JWT sigue vivo vía refresh; el status solo se respeta si se filtra aquí).
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;
    RETURN vault.create_secret(p_secret, p_name, p_description);
END;
$function$;

CREATE OR REPLACE FUNCTION public.pgsec_read_secret(p_id uuid)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    -- Fail-closed: `anon` NUNCA puede leer secretos, aunque alguien re-otorgue el EXECUTE.
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN NULL;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active' (W1 sigue: NO operator).
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN NULL;
        END IF;
    END IF;
    RETURN (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_id);
END;
$function$;

CREATE OR REPLACE FUNCTION public.pgsec_update_secret(p_id uuid, p_secret text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN;
        END IF;
    END IF;
    PERFORM vault.update_secret(p_id, p_secret);
END;
$function$;

CREATE OR REPLACE FUNCTION public.pgsec_delete_secret(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN;
        END IF;
    END IF;
    DELETE FROM vault.secrets WHERE id = p_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.pgsec_upsert_secret(p_name text, p_secret text, p_description text DEFAULT ''::text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_id    uuid;
    v_owner uuid;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;
    SELECT id INTO v_id FROM vault.secrets WHERE name = p_name LIMIT 1;
    IF v_id IS NOT NULL THEN
        PERFORM vault.update_secret(v_id, p_secret);
        RETURN v_id;
    ELSE
        RETURN vault.create_secret(p_secret, p_name, p_description);
    END IF;
END;
$function$;

-- ── A9/M14 (función): get_aveonline_credentials — credenciales del carrier = secretos:
--    mismo criterio que pgsec (owner/manager + active; W1: NO operator). La consola de
--    integraciones ya redirige operators; el API la usa con service_role.
CREATE OR REPLACE FUNCTION public.get_aveonline_credentials(p_tenant_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'vault', 'pg_catalog'
AS $function$
DECLARE
    v_creds   JSONB;
    v_secret  TEXT;
    v_pass_id UUID;
BEGIN
    -- Fail-closed: `anon` NUNCA lee credenciales, aunque alguien re-otorgue el EXECUTE.
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    -- Verificación tenant_users (solo authenticated del tenant vía API).
    -- service_role bypasa porque maneja todos los tenants.
    -- Track9/A9: owner/manager + status='active' (antes: cualquier miembro, incluso
    -- desactivado, leía usuario+password del carrier).
    IF auth.uid() IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = p_tenant_id AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT credentials INTO v_creds
    FROM public.tenant_integrations
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline'
      AND status = 'connected'
    LIMIT 1;

    IF v_creds IS NULL THEN
        RETURN NULL;
    END IF;

    -- Resolver password desde Vault (si está almacenado).
    v_pass_id := NULLIF(v_creds->>'password_secret_id', '')::uuid;
    IF v_pass_id IS NOT NULL THEN
        SELECT decrypted_secret INTO v_secret
        FROM vault.decrypted_secrets WHERE id = v_pass_id;
        IF v_secret IS NOT NULL THEN
            v_creds := v_creds || jsonb_build_object('password', v_secret);
        END IF;
    END IF;

    RETURN v_creds;
END;
$function$;

-- ── A9 (policies public): membresía/rol leído de tenant_users SIN filtro de status ────
-- Recreadas con el MISMO alcance + status='active'. offboarding_log además migra su
-- chequeo de rol del JWT claim a app_current_role() (rol fresco — ver tier bajos).

DROP POLICY IF EXISTS "Tenants can manage their own AI agent" ON public.ai_agents;
CREATE POLICY "Tenants can manage their own AI agent" ON public.ai_agents
  FOR ALL TO authenticated
  USING (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                        WHERE tu.user_id = auth.uid() AND tu.status = 'active'))
  WITH CHECK (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                             WHERE tu.user_id = auth.uid() AND tu.status = 'active'));

DROP POLICY IF EXISTS tenant_isolation_consent_audit_log ON public.consent_audit_log;
CREATE POLICY tenant_isolation_consent_audit_log ON public.consent_audit_log
  FOR SELECT TO authenticated
  USING (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                        WHERE tu.user_id = auth.uid() AND tu.status = 'active'));

DROP POLICY IF EXISTS tenant_isolation_pii_access_log ON public.pii_access_log;
CREATE POLICY tenant_isolation_pii_access_log ON public.pii_access_log
  FOR SELECT TO authenticated
  USING (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                        WHERE tu.user_id = auth.uid() AND tu.status = 'active'));

DROP POLICY IF EXISTS retention_policies_tenant_modify ON public.retention_policies;
CREATE POLICY retention_policies_tenant_modify ON public.retention_policies
  FOR ALL TO authenticated
  USING (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                        WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                          AND tu.role IN ('owner', 'manager')))
  WITH CHECK (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                             WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                               AND tu.role IN ('owner', 'manager')));

DROP POLICY IF EXISTS retention_policies_tenant_select ON public.retention_policies;
CREATE POLICY retention_policies_tenant_select ON public.retention_policies
  FOR SELECT TO authenticated
  USING ((tenant_id IS NULL) OR (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                                                WHERE tu.user_id = auth.uid() AND tu.status = 'active')));

DROP POLICY IF EXISTS legal_acceptance_tenant_insert ON public.tenant_legal_acceptance;
CREATE POLICY legal_acceptance_tenant_insert ON public.tenant_legal_acceptance
  FOR INSERT TO authenticated
  WITH CHECK (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                             WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                               AND tu.role IN ('owner', 'manager')));

DROP POLICY IF EXISTS legal_acceptance_tenant_select ON public.tenant_legal_acceptance;
CREATE POLICY legal_acceptance_tenant_select ON public.tenant_legal_acceptance
  FOR SELECT TO authenticated
  USING (tenant_id IN (SELECT tu.tenant_id FROM public.tenant_users tu
                        WHERE tu.user_id = auth.uid() AND tu.status = 'active'));

DROP POLICY IF EXISTS tenant_offboarding_log_owner_select ON public.tenant_offboarding_log;
CREATE POLICY tenant_offboarding_log_owner_select ON public.tenant_offboarding_log
  FOR SELECT TO authenticated
  USING (tenant_id = public.app_current_tenant() AND public.app_current_role() = 'owner');

-- ── A9 (policies storage): buckets consent-evidence y tenant-inbox-media — mismas
--    subconsultas tenant_users + status='active' (sin tocar la lógica de carpeta=bucket).
--    Nota: la variante _read no chequeaba rol; se le añade SOLO status (alcance idéntico).

DROP POLICY IF EXISTS consent_evidence_tenant_read ON storage.objects;
CREATE POLICY consent_evidence_tenant_read ON storage.objects
  FOR SELECT TO authenticated
  USING (bucket_id = 'consent-evidence'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1));

DROP POLICY IF EXISTS consent_evidence_tenant_write ON storage.objects;
CREATE POLICY consent_evidence_tenant_write ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'consent-evidence'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1)
         AND EXISTS (SELECT 1 FROM public.tenant_users tu
                     WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                       AND tu.role IN ('owner', 'manager')));

DROP POLICY IF EXISTS consent_evidence_tenant_delete ON storage.objects;
CREATE POLICY consent_evidence_tenant_delete ON storage.objects
  FOR DELETE TO authenticated
  USING (bucket_id = 'consent-evidence'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1)
         AND EXISTS (SELECT 1 FROM public.tenant_users tu
                     WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                       AND tu.role IN ('owner', 'manager')));

DROP POLICY IF EXISTS inbox_media_tenant_read ON storage.objects;
CREATE POLICY inbox_media_tenant_read ON storage.objects
  FOR SELECT TO authenticated
  USING (bucket_id = 'tenant-inbox-media'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1));

DROP POLICY IF EXISTS inbox_media_tenant_write ON storage.objects;
CREATE POLICY inbox_media_tenant_write ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'tenant-inbox-media'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1));

DROP POLICY IF EXISTS inbox_media_tenant_delete ON storage.objects;
CREATE POLICY inbox_media_tenant_delete ON storage.objects
  FOR DELETE TO authenticated
  USING (bucket_id = 'tenant-inbox-media'
         AND (storage.foldername(name))[1] = (SELECT (tu.tenant_id)::text FROM public.tenant_users tu
                                               WHERE tu.user_id = auth.uid() AND tu.status = 'active' LIMIT 1)
         AND EXISTS (SELECT 1 FROM public.tenant_users tu
                     WHERE tu.user_id = auth.uid() AND tu.status = 'active'
                       AND tu.role IN ('owner', 'manager')));

-- PostgREST cachea el esquema: la vista payments_safe debe aparecer sin reiniciar.
NOTIFY pgrst, 'reload schema';
