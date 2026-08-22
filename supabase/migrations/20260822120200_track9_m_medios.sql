-- =============================================================================
-- Track 9 / Tier MEDIO (M1-M14) — lockdown de tablas de infra, gates de rol en
-- configs críticas, append-only conversacional, WITH CHECK faltantes, retención PII
-- Fecha: 2026-08-22 · Origen: PLAN-CIERRE §Track 9 · Tests: tests/dbharness/test_track9_m_medios.py
-- (los 16 ataques ejecutaban antes de este fix; positivos verificados pre y post)
--
-- Verificación de callers (grep 2026-08-22): apps/web NUNCA escribe vía PostgREST en
-- conversations/messages/contacts/shipments/order_tracking/marketplace_listings/rma/
-- cancellation_policy/shipping_provider_config — toda mutación va por la API
-- (service_role, que bypasa RLS). Los gates de rol de este tier son por tanto
-- invisibles para la consola y cierran el curl con JWT de operator.
-- =============================================================================

-- ── M1-M4: tablas de infra pura → service_role-only ──────────────────────────
-- integration_oauth_states (M1), idempotency_keys (M2), wompi_events_seen +
-- webhook_events_seen (M3 — dedup de webhooks de pago: borrarlas = re-procesar cobros),
-- tenant_usage_counters/events (M4 — cuotas de plan), outbound_idempotency_cache
-- (M12-tabla, misma familia). Patrón tabla-infra de 20260802120000.
DO $$
DECLARE
  v_tabla TEXT;
BEGIN
  FOREACH v_tabla IN ARRAY ARRAY[
    'integration_oauth_states', 'idempotency_keys', 'wompi_events_seen',
    'webhook_events_seen', 'tenant_usage_counters', 'tenant_usage_events',
    'outbound_idempotency_cache'
  ] LOOP
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', v_tabla);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', v_tabla);
  END LOOP;
END $$;

-- ── M5: tenant_shipping_provider_config — ¡real_guides_enabled! Un operator con curl
--        podía activar guías REALES (facturación en la cuenta del carrier del tenant).
DROP POLICY IF EXISTS track9_tspc_insert_privileged ON public.tenant_shipping_provider_config;
CREATE POLICY track9_tspc_insert_privileged ON public.tenant_shipping_provider_config AS RESTRICTIVE
  FOR INSERT TO authenticated WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_tspc_update_privileged ON public.tenant_shipping_provider_config;
CREATE POLICY track9_tspc_update_privileged ON public.tenant_shipping_provider_config AS RESTRICTIVE
  FOR UPDATE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_tspc_delete_privileged ON public.tenant_shipping_provider_config;
CREATE POLICY track9_tspc_delete_privileged ON public.tenant_shipping_provider_config AS RESTRICTIVE
  FOR DELETE TO authenticated USING (public.app_current_role() IN ('owner', 'manager'));

-- ── M6: tenant_cancellation_policy — reglas legales de cancelación/retracto del tenant.
DROP POLICY IF EXISTS track9_tcp_insert_privileged ON public.tenant_cancellation_policy;
CREATE POLICY track9_tcp_insert_privileged ON public.tenant_cancellation_policy AS RESTRICTIVE
  FOR INSERT TO authenticated WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_tcp_update_privileged ON public.tenant_cancellation_policy;
CREATE POLICY track9_tcp_update_privileged ON public.tenant_cancellation_policy AS RESTRICTIVE
  FOR UPDATE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_tcp_delete_privileged ON public.tenant_cancellation_policy;
CREATE POLICY track9_tcp_delete_privileged ON public.tenant_cancellation_policy AS RESTRICTIVE
  FOR DELETE TO authenticated USING (public.app_current_role() IN ('owner', 'manager'));

-- ── M7: rma_requests — devoluciones = dinero del cliente (mismo criterio que claims/A5).
DROP POLICY IF EXISTS track9_rma_update_privileged ON public.rma_requests;
CREATE POLICY track9_rma_update_privileged ON public.rma_requests AS RESTRICTIVE
  FOR UPDATE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'))
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
DROP POLICY IF EXISTS track9_rma_no_delete ON public.rma_requests;
CREATE POLICY track9_rma_no_delete ON public.rma_requests AS RESTRICTIVE
  FOR DELETE TO authenticated USING (false);

-- ── M8: marketplace_listings / shipments / order_tracking — estado operativo y forense
--        de envíos/listings. La consola solo LEE (el write real es de la API/workers).
DO $$
DECLARE
  v_tabla TEXT;
BEGIN
  FOREACH v_tabla IN ARRAY ARRAY['marketplace_listings', 'shipments', 'order_tracking'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS track9_%I_write_privileged ON public.%I', v_tabla, v_tabla);
    EXECUTE format(
      'CREATE POLICY track9_%I_write_privileged ON public.%I AS RESTRICTIVE
         FOR INSERT TO authenticated WITH CHECK (public.app_current_role() IN (''owner'', ''manager''))',
      v_tabla, v_tabla);
    EXECUTE format('DROP POLICY IF EXISTS track9_%I_update_privileged ON public.%I', v_tabla, v_tabla);
    EXECUTE format(
      'CREATE POLICY track9_%I_update_privileged ON public.%I AS RESTRICTIVE
         FOR UPDATE TO authenticated
         USING (public.app_current_role() IN (''owner'', ''manager''))
         WITH CHECK (public.app_current_role() IN (''owner'', ''manager''))',
      v_tabla, v_tabla);
    EXECUTE format('DROP POLICY IF EXISTS track9_%I_delete_privileged ON public.%I', v_tabla, v_tabla);
    EXECUTE format(
      'CREATE POLICY track9_%I_delete_privileged ON public.%I AS RESTRICTIVE
         FOR DELETE TO authenticated USING (public.app_current_role() IN (''owner'', ''manager''))',
      v_tabla, v_tabla);
  END LOOP;
END $$;

-- ── M9: notification_settings — config lleva secret refs de canales (bot_token Vault id,
--        chat_ids). SELECT solo owner/manager (la página de integraciones ya redirige
--        operators; el write_privileged existente se moderniza en el tier de bajos).
DROP POLICY IF EXISTS track9_notification_settings_select_privileged ON public.notification_settings;
CREATE POLICY track9_notification_settings_select_privileged ON public.notification_settings AS RESTRICTIVE
  FOR SELECT TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'));

-- ── M10: append-only conversacional — la conversación ES el contrato (G-8, Ley 1480).
--        Nadie edita/borra mensajes, conversaciones ni contactos por PostgREST.
DO $$
DECLARE
  v_tabla TEXT;
BEGIN
  FOREACH v_tabla IN ARRAY ARRAY['messages', 'conversations', 'contacts'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS track9_%I_no_update ON public.%I', v_tabla, v_tabla);
    EXECUTE format(
      'CREATE POLICY track9_%I_no_update ON public.%I AS RESTRICTIVE
         FOR UPDATE TO authenticated USING (false)',
      v_tabla, v_tabla);
    EXECUTE format('DROP POLICY IF EXISTS track9_%I_no_delete ON public.%I', v_tabla, v_tabla);
    EXECUTE format(
      'CREATE POLICY track9_%I_no_delete ON public.%I AS RESTRICTIVE
         FOR DELETE TO authenticated USING (false)',
      v_tabla, v_tabla);
  END LOOP;
END $$;

-- ── M11: conversation_notes_author_update — no tenía WITH CHECK: un UPDATE podía MOVER
--        la nota a otro tenant (fuga de contenido interno). WITH CHECK exige que la fila
--        NUEVA permanezca en el tenant del caller (anti-salto) Y que el caller sea el
--        autor o un privilegiado; rol fresco vía app_current_role, no el claim del JWT.
DROP POLICY IF EXISTS conversation_notes_author_update ON public.conversation_notes;
CREATE POLICY conversation_notes_author_update ON public.conversation_notes
  FOR UPDATE TO authenticated
  USING ((author_user_id = auth.uid())
         OR (tenant_id = public.app_current_tenant()
             AND public.app_current_role() IN ('owner', 'manager')))
  WITH CHECK (tenant_id = public.app_current_tenant()
         AND ((author_user_id = auth.uid())
              OR public.app_current_role() IN ('owner', 'manager')));

-- ── M12: outbound_idempotency_lookup/register → service_role (callers:
--        api/lib/integration_client/idempotency.py y worker.py, ambos service_role).
REVOKE ALL ON FUNCTION public.outbound_idempotency_lookup(text, uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.outbound_idempotency_register(text, uuid, text, integer, jsonb, jsonb, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.outbound_idempotency_lookup(text, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.outbound_idempotency_register(text, uuid, text, integer, jsonb, jsonb, integer) TO service_role;

-- ── M13: pii_access_log — el trigger append-only bloqueaba INCONDICIONALMENTE, incluida
--        la retención (fn_apply_retention corre con service_role): la supresión de PII
--        vencida (Ley 1581) estaba rota en silencio. El trigger ahora deja pasar a los
--        roles de backend/admin; cualquier rol de cliente sigue bloqueado (de hecho el
--        ACL/RLS de la tabla ya lo frena antes de llegar aquí — defensa en capas).
CREATE OR REPLACE FUNCTION public.pii_access_log_block_modify()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    -- Track9/M13: la retención y los admins SÍ pueden purgar (la ley MANDA suprimir
    -- PII vencida); el bloqueo es para roles de cliente vía PostgREST.
    IF current_user IN ('service_role', 'postgres', 'supabase_admin', 'supabase_storage_admin') THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'pii_access_log es append-only (Ley 1581 Art. 9)';
END;
$function$;

-- ── M14: storage legacy tenant-media — VERIFICADO 2026-08-22: 0 objetos en STG y el
--        bucket público sigue en uso legítimo (imágenes del catálogo van por URL
--        pública a WhatsApp). Sin acción de esquema; la purga de objetos legacy en
--        PRD queda como paso operativo del descongelamiento (ver bitácora PLAN.md §E).
