-- BLOQUE G-2 — RPC de ventas NETAS (confirmadas − reembolsos) para el KPI del home.
--
-- Semántica (decisión founder, versión completa):
--   revenue = ventas brutas confirmadas − reembolsos, en dos ventanas (hoy, mes),
--   timezone Colombia (America/Bogota, UTC-5 sin DST).
--
-- VENTAS BRUTAS = SUM(orders.total_amount) de pedidos con pago reconocido
--   (status IN confirmed/processing/shipped/delivered = PAID_ORDER_STATUSES del P&L,
--   apps/web/app/dashboard/finance/lib/pnl.ts), por fecha de CREACIÓN del pedido.
--   total_amount = DECIMAL(10,2) en pesos.
--
-- REEMBOLSOS — se netean por FECHA DE REEMBOLSO (no la del pedido), de 3 fuentes:
--   1) CANCELACIONES (order_cancellations): el pedido pasa a 'cancelled' → YA queda
--      fuera de las ventas brutas por el filtro de status. NO se resta (evita
--      doble-conteo). Es la "exclusión por status" del modelo.
--   2) RECLAMOS (claims status='refunded'): el reembolso post-venta NO cambia
--      orders.status (y 'delivered' es terminal) → el pedido sigue contado, hay que
--      restar. Monto = claims.refunded_amount (pesos REALES capturados al reembolsar,
--      no el requested_amount = intención — ver 20260712010000). Fecha = refunded_at
--      (write-once, estable ante ediciones). Solo sobre pedidos aún en el set contado
--      (JOIN a orders) → evita restar reembolsos de pedidos ya cancelados.
--   3) RMA / retracto Ley 1480 (rma_requests): la devolución tampoco cambia
--      orders.status (no existe 'returned' en orders) → sigue contado, hay que
--      restar. Monto = refund_amount_cents/100 (CENTAVOS → pesos). Fecha real =
--      refund_completed_at (NULL hasta completarse → solo reembolsos ya ejecutados).
--
-- El neto PUEDE ser negativo en una ventana con más reembolsos que ventas nuevas
-- (p. ej. reembolso hoy de un pedido de ayer): es correcto (actividad neta del período).
--
-- SEGURIDAD (ADR-0025): SECURITY INVOKER → la RLS "Tenant Isolation" de orders,
-- claims (app_current_tenant, fix 20260416000000) y rma_requests aplica bajo el JWT
-- del caller. Además se filtra explícito por public.app_current_tenant() en las 3
-- fuentes (belt+suspenders) y NO se recibe tenant_id por parámetro (no spoofeable).
-- STABLE: solo lee.

CREATE OR REPLACE FUNCTION public.rpc_dashboard_revenue()
RETURNS TABLE (revenue_today numeric, revenue_month numeric)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
  WITH b AS (
    SELECT
      timezone('America/Bogota', date_trunc('day',   timezone('America/Bogota', now()))) AS day_start,
      timezone('America/Bogota', date_trunc('month', timezone('America/Bogota', now()))) AS month_start
  ),
  tid AS (SELECT public.app_current_tenant() AS t),
  gross AS (
    SELECT
      COALESCE(SUM(o.total_amount) FILTER (WHERE o.created_at >= b.day_start),   0) AS today,
      COALESCE(SUM(o.total_amount) FILTER (WHERE o.created_at >= b.month_start), 0) AS month
    FROM b, tid, public.orders o
    WHERE o.tenant_id = tid.t
      AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
      AND o.created_at >= b.month_start
  ),
  claim_refunds AS (
    SELECT
      COALESCE(SUM(c.refunded_amount) FILTER (WHERE c.refunded_at >= b.day_start),   0) AS today,
      COALESCE(SUM(c.refunded_amount) FILTER (WHERE c.refunded_at >= b.month_start), 0) AS month
    FROM b, tid, public.claims c
    JOIN public.orders o
      ON o.id = c.order_id
     AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
    WHERE c.tenant_id = tid.t
      AND c.status = 'refunded'
      AND c.refunded_amount IS NOT NULL
      AND c.refunded_at >= b.month_start
  ),
  rma_refunds AS (
    SELECT
      COALESCE(SUM(r.refund_amount_cents) FILTER (WHERE r.refund_completed_at >= b.day_start),   0) / 100.0 AS today,
      COALESCE(SUM(r.refund_amount_cents) FILTER (WHERE r.refund_completed_at >= b.month_start), 0) / 100.0 AS month
    FROM b, tid, public.rma_requests r
    JOIN public.orders o
      ON o.id = r.order_id
     AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
    WHERE r.tenant_id = tid.t
      AND r.refund_completed_at IS NOT NULL
      AND r.refund_completed_at >= b.month_start
  )
  SELECT
    -- ROUND a 2 decimales: el /100.0 de RMA introduce precisión numérica larga.
    ROUND((gross.today - claim_refunds.today - rma_refunds.today)::numeric, 2)  AS revenue_today,
    ROUND((gross.month - claim_refunds.month - rma_refunds.month)::numeric, 2)  AS revenue_month
  FROM gross, claim_refunds, rma_refunds;
$$;

REVOKE ALL ON FUNCTION public.rpc_dashboard_revenue() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_dashboard_revenue() TO authenticated;
