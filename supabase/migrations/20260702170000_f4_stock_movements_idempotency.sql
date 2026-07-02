-- F4 (roadmap producción) — idempotencia de movimientos de stock ligados a una orden.
--
-- Previene el DOBLE DECREMENTO/RESTAURO de stock: un reintento de webhook (Wompi) o un doble
-- procesamiento no debe insertar 2 veces el MISMO movimiento (misma orden + variación + tipo) →
-- stock descontado/restaurado dos veces (oversell o inflado).
--
-- PREDICADO CORREGIDO respecto al roadmap: el índice incluye `reason`, NO solo (order_id, variation_id).
-- Verificado en código (order_cancellation.py L635): un 'cancellation_refund' reusa el MISMO order_id que
-- el 'sale'/'reservation_consumed' original. Un UNIQUE (order_id, variation_id) a secas ROMPERÍA el refund
-- (colisión con el movimiento de venta). Incluir `reason` permite el ciclo legítimo venta→refund y a la vez
-- bloquea el duplicado exacto (mismo tipo) por reintento.
--
-- WHERE order_id IS NOT NULL: los ajustes manuales de inventario (sin orden) no se restringen.
-- Verificado pre-aplicación: 0 duplicados en (order_id, variation_id) → seguro. Idempotente (IF NOT EXISTS).

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_movements_order_variation_reason
  ON public.stock_movements (order_id, variation_id, reason)
  WHERE order_id IS NOT NULL;
