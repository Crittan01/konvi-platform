-- =============================================================================
-- F2 Despachos — purga programada de cotizaciones huérfanas (pg_cron).
--
-- Contexto: el endpoint DELETE /api/v1/shipping/orphans existe pero no tiene
-- caller (ni UI ni cron). El bot y el cotizador insertan filas
-- shipments(status='quoted', selected_rate NULL) por cada estimación; la tabla
-- crece sin límite. services/cron es Fase 13 (futuro), así que la retención se
-- delega a pg_cron dentro de Postgres.
--
-- Diseño:
--   • Función SECURITY DEFINER que borra TODAS las cotizaciones huérfanas
--     (todos los tenants) con status='quoted', selected_rate NULL y
--     created_at < NOW() - 30 días. Misma semántica que purge_orphan_quotes()
--     en services/api/routers/shipping.py, pero cross-tenant y sin RLS
--     (bypass legítimo de mantenimiento).
--   • Se agenda con cron.schedule() si la extensión pg_cron está disponible.
--     Idempotente: unschedule previo por nombre de job.
--
-- Retención: 30 días (corta, coincide con el endpoint manual). Ajustar el
-- literal si el negocio requiere otra ventana.
--
-- NO aplicada por esta tarea. Si pg_cron no está instalado en el proyecto
-- Supabase, el bloque DO se salta silenciosamente y solo queda la función
-- (invocable manualmente vía SELECT public.fn_purge_orphan_shipment_quotes()).
--
-- Idempotente: CREATE OR REPLACE FUNCTION + guard de extensión + unschedule.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.fn_purge_orphan_shipment_quotes(
    p_retention_days INTEGER DEFAULT 30
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    WITH purged AS (
        DELETE FROM public.shipments
        WHERE status = 'quoted'
          AND selected_rate IS NULL
          AND created_at < NOW() - (p_retention_days || ' days')::interval
        RETURNING id
    )
    SELECT COUNT(*) INTO v_deleted FROM purged;

    RAISE NOTICE 'fn_purge_orphan_shipment_quotes: % filas eliminadas (retención % días)',
        v_deleted, p_retention_days;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION public.fn_purge_orphan_shipment_quotes(INTEGER) IS
    'Mantenimiento: elimina cotizaciones huérfanas (quoted + selected_rate NULL '
    '+ > N días). Cross-tenant, SECURITY DEFINER. Agendada vía pg_cron. '
    'Espejo del endpoint manual DELETE /shipping/orphans.';

REVOKE ALL ON FUNCTION public.fn_purge_orphan_shipment_quotes(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fn_purge_orphan_shipment_quotes(INTEGER) TO service_role;

-- ─── Agendar con pg_cron (si está disponible) ───────────────────────────────
DO $cron$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        -- Idempotente: quitar el job previo si ya existía.
        PERFORM cron.unschedule('purge-orphan-shipment-quotes')
        WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'purge-orphan-shipment-quotes'
        );
        -- Diario 03:15 UTC.
        PERFORM cron.schedule(
            'purge-orphan-shipment-quotes',
            '15 3 * * *',
            $job$SELECT public.fn_purge_orphan_shipment_quotes(30);$job$
        );
        RAISE NOTICE 'pg_cron job purge-orphan-shipment-quotes agendado (03:15 UTC diario).';
    ELSE
        RAISE NOTICE 'pg_cron no instalado — fn_purge_orphan_shipment_quotes queda invocable manualmente.';
    END IF;
END
$cron$;
