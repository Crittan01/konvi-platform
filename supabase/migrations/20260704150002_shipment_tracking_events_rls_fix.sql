-- =============================================================================
-- F2 Despachos — fix RLS de shipment_tracking_events para el timeline de la
-- consola.
--
-- Problema: la policy original (20260529000000_shipment_tracking_events.sql)
-- usa `current_setting('app.current_tenant_id', true)::uuid` directo. Ese GUC
-- NO está seteado en los Server Components de Next.js (createClient() con
-- cookie auth-user) → la policy retorna FALSE → 0 rows → el timeline de
-- /dashboard/shipping nunca muestra eventos aunque existan.
--
-- Es el MISMO defecto que corrigió 20260527030000_aveonline_rls_fix.sql para
-- tenant_shipping_provider_config. Patrón canónico del repo: usar
-- app_current_tenant() (COALESCE GUC ↔ JWT claim), que soporta a la vez
-- workers (GUC) y server components (JWT).
--
-- Degradación segura: mientras esta migración NO esté aplicada, el código de
-- page.tsx envuelve la query en try/catch y degrada a "sin timeline" — el
-- historial de envíos sigue funcionando.
--
-- Idempotente: DROP POLICY IF EXISTS + CREATE.
-- =============================================================================

DROP POLICY IF EXISTS shipment_tracking_events_tenant_isolation
    ON public.shipment_tracking_events;

CREATE POLICY shipment_tracking_events_tenant_isolation
    ON public.shipment_tracking_events
    FOR SELECT
    USING (tenant_id = app_current_tenant());

COMMENT ON POLICY shipment_tracking_events_tenant_isolation
    ON public.shipment_tracking_events IS
    'Tenant isolation usando app_current_tenant() — soporta workers (GUC) Y '
    'server components Next.js (JWT claim). Reemplaza current_setting() directo '
    'que rompía el timeline en la consola. INSERT sigue siendo service_role.';
