-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: ai_insights (cache por tenant/módulo) + metrics_orders_summary RPC
-- Módulo Métricas + Insights IA (F4 2026-07-04).
--
-- Dos piezas independientes, ambas idempotentes y sin datos destructivos:
--
-- 1) public.ai_insights — persiste el ÚLTIMO análisis IA por (tenant_id, módulo).
--    Decisión F4: persistir el último insight ya (barato, mejora DX, evita
--    regenerar/gastar tokens Gemini al navegar). La cuota-por-plan queda atada
--    al billing cuando se defina; el default de 10/h vive en la ruta.
--    Fallback: si la tabla no existe, la ruta hace feature-detect (try/catch) y
--    el panel cae a estado 'idle' sin persistencia.
--
-- 2) public.metrics_orders_summary(p_from, p_to) — agregación EXACTA a escala de
--    ingresos/ventas de pedidos, sin el cap de 1000 filas de PostgREST. El
--    cliente hace feature-detect: si el RPC no existe, cae a la aproximación
--    client-side acotada por ventana (aggregateOrders) + flag de truncamiento.
--    Definición canónica de ingreso alineada con Finanzas (PAID_ORDER_STATUSES).
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1) Cache de insights IA ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.ai_insights (
  tenant_id    UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  module       TEXT NOT NULL CHECK (module IN ('inventory', 'orders', 'contacts', 'metrics')),
  result       JSONB NOT NULL,               -- InsightResult completo (resumen, hallazgos, acciones, alerta, generated_at, tokens_used)
  tokens_used  INTEGER,                       -- snapshot para accounting/abuso
  generated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, module)             -- una fila por tenant por módulo (upsert)
);

ALTER TABLE public.ai_insights ENABLE ROW LEVEL SECURITY;

-- Aislamiento por tenant (ADR-0025): app_current_tenant() lee el claim del JWT
-- (clientes web) o el GUC app.current_tenant_id (workers).
DROP POLICY IF EXISTS tenant_isolation_ai_insights ON public.ai_insights;
CREATE POLICY tenant_isolation_ai_insights
  ON public.ai_insights
  FOR ALL
  USING (tenant_id = app_current_tenant())
  WITH CHECK (tenant_id = app_current_tenant());

-- Trigger updated_at
CREATE OR REPLACE FUNCTION public.ai_insights_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ai_insights_updated_at_trg ON public.ai_insights;
CREATE TRIGGER ai_insights_updated_at_trg
  BEFORE UPDATE ON public.ai_insights
  FOR EACH ROW
  EXECUTE FUNCTION public.ai_insights_set_updated_at();

COMMENT ON TABLE public.ai_insights IS
  'Cache del último análisis IA (Gemini) por tenant y módulo. Decisión F4: '
  'persistencia para evitar regenerar/gastar tokens al navegar. Upsert on '
  '(tenant_id, module). RLS por tenant (ADR-0025).';

-- ── 2) Agregación exacta de pedidos por ventana (sin cap PostgREST) ───────────
-- SECURITY DEFINER + filtro tenant EXPLÍCITO derivado del JWT (patrón canónico
-- de get_tenant_team). Devuelve UNA fila con conteos y sumas de ingreso.
--   recognized_revenue = ingreso reconocido (PAID_ORDER_STATUSES = confirmed+)
--   gross_sales        = ventas brutas (no canceladas) — métrica secundaria
--   delivered_revenue  = solo entregados (dinero ya realizado)

DROP FUNCTION IF EXISTS public.metrics_orders_summary(timestamptz, timestamptz);

CREATE OR REPLACE FUNCTION public.metrics_orders_summary(
  p_from TIMESTAMPTZ DEFAULT NULL,
  p_to   TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
  orders_total         BIGINT,
  orders_non_cancelled BIGINT,
  orders_cancelled     BIGINT,
  gross_sales          NUMERIC,
  recognized_revenue   NUMERIC,
  delivered_revenue    NUMERIC,
  by_status            JSONB
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant uuid;
BEGIN
  v_tenant := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid;
  IF v_tenant IS NULL THEN
    RETURN; -- sin contexto de tenant → vacío (el cliente cae a fallback)
  END IF;

  RETURN QUERY
  WITH o AS (
    SELECT status::text AS status, COALESCE(total_amount, 0)::numeric AS amt
    FROM public.orders
    WHERE tenant_id = v_tenant
      AND (p_from IS NULL OR created_at >= p_from)
      AND (p_to   IS NULL OR created_at <  p_to)
  ),
  bs AS (
    SELECT jsonb_object_agg(status, c) AS js
    FROM (SELECT status, COUNT(*) AS c FROM o GROUP BY status) g
  )
  SELECT
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE status <> 'cancelled')::bigint,
    COUNT(*) FILTER (WHERE status = 'cancelled')::bigint,
    COALESCE(SUM(amt) FILTER (WHERE status <> 'cancelled'), 0)::numeric,
    COALESCE(SUM(amt) FILTER (WHERE status IN ('confirmed', 'processing', 'shipped', 'delivered')), 0)::numeric,
    COALESCE(SUM(amt) FILTER (WHERE status = 'delivered'), 0)::numeric,
    COALESCE((SELECT js FROM bs), '{}'::jsonb)
  FROM o;
END;
$$;

GRANT EXECUTE ON FUNCTION public.metrics_orders_summary(timestamptz, timestamptz) TO authenticated;

COMMENT ON FUNCTION public.metrics_orders_summary(timestamptz, timestamptz) IS
  'Agregación exacta de pedidos por ventana [p_from, p_to) para un tenant '
  '(derivado del JWT). Evita el cap de 1000 filas de PostgREST en el cálculo de '
  'ingresos. recognized_revenue = confirmed+ (canónico, = Finanzas). F4.';
