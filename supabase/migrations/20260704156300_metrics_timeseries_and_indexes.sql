-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: metrics_orders_timeseries (serie por período / MoM) + índices de
-- soporte para agregación exacta a escala. Módulo Métricas/Finanzas/Dashboard
-- (F-transversales 2026-07-04). Idempotente y sin datos destructivos.
--
-- Contexto (decisión "verdad numérica a escala"):
--   • metrics_orders_summary(from,to) YA existe (20260704154000) → agregación
--     EXACTA de un período único (revenue/counts/by_status). La comparativa MoM
--     de dos puntos ya se resuelve llamando ese RPC dos veces (pctDelta).
--   • FALTA la variante POR-PERÍODO: una SERIE temporal bucketed (día/semana/mes)
--     para la tendencia MoM a escala (>1000 pedidos), imposible client-side bajo
--     el cap de PostgREST. Este RPC la agrega server-side en hora Colombia.
--
-- Adopción: expand-phase. El RPC queda GRANTeado y comentado; el cliente
-- (metrics/finance/dashboard) lo adopta por feature-detect en un cambio aparte
-- (esos módulos degradan seguro a la aproximación client-side si el RPC falta).
--
-- Alineación de ingreso: recognized_revenue = PAID_ORDER_STATUSES (confirmed+),
-- idéntico a metrics_orders_summary y a Finanzas. NO redefinir el set aquí.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1) Serie temporal exacta de pedidos por bucket (día/semana/mes) ───────────
-- SECURITY DEFINER + filtro tenant EXPLÍCITO derivado del JWT (patrón canónico
-- de metrics_orders_summary). Buckets en America/Bogota para empatar con la
-- agrupación temporal del cliente (lib/date-window). p_bucket validado contra
-- una lista blanca (no interpolación libre en date_trunc).

DROP FUNCTION IF EXISTS public.metrics_orders_timeseries(timestamptz, timestamptz, text);

CREATE OR REPLACE FUNCTION public.metrics_orders_timeseries(
  p_from   TIMESTAMPTZ DEFAULT NULL,
  p_to     TIMESTAMPTZ DEFAULT NULL,
  p_bucket TEXT        DEFAULT 'month'
)
RETURNS TABLE (
  bucket_start         TIMESTAMPTZ,
  orders_total         BIGINT,
  orders_non_cancelled BIGINT,
  recognized_revenue   NUMERIC,
  gross_sales          NUMERIC
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant uuid;
  v_bucket text;
BEGIN
  v_tenant := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid;
  IF v_tenant IS NULL THEN
    RETURN; -- sin contexto de tenant → vacío (el cliente cae a fallback)
  END IF;

  -- Lista blanca: date_trunc solo admite estos campos; evita inyección vía p_bucket.
  v_bucket := lower(coalesce(p_bucket, 'month'));
  IF v_bucket NOT IN ('day', 'week', 'month') THEN
    v_bucket := 'month';
  END IF;

  RETURN QUERY
  WITH o AS (
    SELECT
      -- Trunca en hora Colombia y reconvierte a timestamptz para que el bucket
      -- represente el inicio real del día/semana/mes local (no UTC).
      (date_trunc(v_bucket, (created_at AT TIME ZONE 'America/Bogota'))
        AT TIME ZONE 'America/Bogota') AS bstart,
      status::text                     AS status,
      COALESCE(total_amount, 0)::numeric AS amt
    FROM public.orders
    WHERE tenant_id = v_tenant
      AND (p_from IS NULL OR created_at >= p_from)
      AND (p_to   IS NULL OR created_at <  p_to)
  )
  SELECT
    o.bstart,
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE o.status <> 'cancelled')::bigint,
    COALESCE(SUM(o.amt) FILTER (
      WHERE o.status IN ('confirmed', 'processing', 'shipped', 'delivered')), 0)::numeric,
    COALESCE(SUM(o.amt) FILTER (WHERE o.status <> 'cancelled'), 0)::numeric
  FROM o
  GROUP BY o.bstart
  ORDER BY o.bstart;
END;
$$;

GRANT EXECUTE ON FUNCTION public.metrics_orders_timeseries(timestamptz, timestamptz, text) TO authenticated;

COMMENT ON FUNCTION public.metrics_orders_timeseries(timestamptz, timestamptz, text) IS
  'Serie temporal exacta de pedidos por bucket (day/week/month) en hora Colombia '
  'para un tenant (derivado del JWT). Habilita la tendencia MoM a escala sin el '
  'cap de 1000 filas de PostgREST. recognized_revenue = confirmed+ (= Finanzas). '
  'Complementa metrics_orders_summary (punto único). F-transversales.';

-- ── 2) Índices de soporte para agregación exacta por tenant + ventana ─────────
-- Ambos idempotentes. Aceleran las queries windowed por-tenant que hoy escanean
-- con índices parciales/de una sola columna.

-- messages(tenant_id, created_at): la distribución por día de semana y cualquier
-- conteo de mensajes por ventana filtra por tenant y rango de created_at. Los
-- índices existentes de messages son parciales (solo inbound pending/processing).
CREATE INDEX IF NOT EXISTS idx_messages_tenant_created
  ON public.messages (tenant_id, created_at);

-- audit_log(tenant_id, created_at DESC): el listado de auditoría y las métricas
-- de actividad filtran por tenant y ordenan por created_at DESC. Hoy existen
-- idx_audit_log_tenant (solo tenant_id) e idx_audit_log_created (solo created_at);
-- el compuesto evita el sort/merge en el caso común (un tenant, ventana reciente).
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_created
  ON public.audit_log (tenant_id, created_at DESC);
