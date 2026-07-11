-- =============================================================================
-- BLOQUE C (item 4) — RPC atómico e IDEMPOTENTE de decremento/reposición de stock.
--
-- HALLAZGO (audit + verificado en HEAD): el decremento directo de stock
-- (`_decrement_stock_on_confirm`, orders.py) es un read-modify-write en 2-3 llamadas
-- PostgREST SEPARADAS (SELECT stock → UPDATE valor calculado → INSERT movement), sin
-- transacción ni idempotencia efectiva. El índice único `uq_stock_movements_order_variation_reason`
-- (order_id, variation_id, reason) existe, pero el código NO lo usa como guard: un retry
-- tardío de Wompi (3h/24h) sobre una orden ya confirmada re-entra a _confirm_order y
-- DECREMENTA OTRA VEZ (el UPDATE de stock corre antes de que el INSERT del movement falle) →
-- inventario desinflado (bloquea ventas legítimas con falso 'sin stock'). Además el
-- read-modify-write puede perder decrementos concurrentes (race).
--
-- FIX: RPC transaccional que hace el INSERT del movement PRIMERO con
-- `ON CONFLICT (order_id, variation_id, reason) DO NOTHING RETURNING` como GUARD de
-- idempotencia: si el movimiento ya existe (retry/duplicado), es un NO-OP TOTAL (no toca
-- stock). Solo si el movimiento es NUEVO se aplica el UPDATE de stock. `FOR UPDATE` sobre
-- la variante serializa concurrencia. Espejo `rpc_stock_restore` para reposición (cancelación).
-- Tenant-scoped (ADR-0025) + SECURITY DEFINER (mismo patrón que rpc_stock_reservation_consume).
--
-- Convención de stock negativo: se PRESERVA (stock_quantity - qty puede quedar < 0), igual
-- que el decremento directo actual y que rpc_stock_reservation_consume — el operador ve la
-- alerta de bajo/negativo stock. NO se usa GREATEST(0,...) para no ocultar el over-sell.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. Idempotente
--    (CREATE OR REPLACE). Aditivo puro (nuevas funciones) → no rompe callers existentes
--    (expand-contract: los callers migran en el deploy de código de este bloque).
-- =============================================================================

-- ── Decremento idempotente (reason='sale' por default) ──────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_decrement(
  p_tenant_id    UUID,
  p_variation_id UUID,
  p_qty          INTEGER,
  p_order_id     UUID,
  p_reason       TEXT DEFAULT 'sale'
)
RETURNS INTEGER   -- new_stock resultante (o el actual si fue no-op idempotente)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current   INTEGER;
  v_new       INTEGER;
  v_mov_id    UUID;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_decrement: qty_must_be_positive';
  END IF;
  -- La idempotencia depende del índice parcial WHERE order_id IS NOT NULL: con order_id NULL
  -- el ON CONFLICT no arbitra y cada reintento re-decrementaría. Exigir order_id explícitamente.
  IF p_order_id IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_decrement: order_id_required_for_idempotency';
  END IF;

  -- Lock de la variante (serializa decrementos concurrentes de la misma variante).
  SELECT stock_quantity INTO v_current
    FROM public.product_variations
   WHERE id = p_variation_id AND tenant_id = p_tenant_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_decrement: variation_not_found_or_cross_tenant';
  END IF;

  -- CHECK product_variations_stock_nonneg (20260702150000) prohíbe stock < 0: un v_new
  -- negativo haría fallar el UPDATE y ROLLBACK de toda la RPC (movement no persiste, stock
  -- intacto → revendible sin auditoría). Se clampa a 0; el delta registrado es el cambio REAL
  -- aplicado (v_new - v_current) para que el ledger sea consistente (new_stock = old + delta).
  -- El over-sell (order_items.qty > stock disponible) queda visible al comparar la orden vs el
  -- movimiento; el operador lo gestiona (backorder).
  v_new := GREATEST(0, v_current - p_qty);

  -- GUARD de idempotencia: el movement es la fuente de verdad de "ya se decrementó esto".
  -- Si (order_id, variation_id, reason) ya existe → DO NOTHING → v_mov_id NULL → no-op total.
  INSERT INTO public.stock_movements (tenant_id, variation_id, order_id, delta, new_stock, reason)
  VALUES (p_tenant_id, p_variation_id, p_order_id, v_new - v_current, v_new, p_reason)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO NOTHING
  RETURNING id INTO v_mov_id;

  IF v_mov_id IS NULL THEN
    -- Decremento ya aplicado antes (retry Wompi tardío / webhook duplicado / reconcile) → NO tocar stock.
    RETURN v_current;
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = v_new, updated_at = NOW()
   WHERE id = p_variation_id AND tenant_id = p_tenant_id;

  RETURN v_new;
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_decrement(UUID, UUID, INTEGER, UUID, TEXT) IS
  'BLOQUE C item 4 — decremento atómico e idempotente. INSERT movement (ON CONFLICT order_id,variation_id,reason DO NOTHING) como guard: retry/duplicado = no-op. Solo decrementa stock si el movement es nuevo. Retorna new_stock.';

-- ── Reposición idempotente (reason distinto, ej. 'cancellation_restore') ─────
CREATE OR REPLACE FUNCTION public.rpc_stock_restore(
  p_tenant_id    UUID,
  p_variation_id UUID,
  p_qty          INTEGER,
  p_order_id     UUID,
  p_reason       TEXT DEFAULT 'cancellation_restore'
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current   INTEGER;
  v_new       INTEGER;
  v_mov_id    UUID;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_restore: qty_must_be_positive';
  END IF;
  IF p_order_id IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_restore: order_id_required_for_idempotency';
  END IF;

  SELECT stock_quantity INTO v_current
    FROM public.product_variations
   WHERE id = p_variation_id AND tenant_id = p_tenant_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_restore: variation_not_found_or_cross_tenant';
  END IF;

  v_new := v_current + p_qty;

  -- Mismo guard idempotente: una reposición para (order,variante,razón) se aplica UNA vez.
  INSERT INTO public.stock_movements (tenant_id, variation_id, order_id, delta, new_stock, reason)
  VALUES (p_tenant_id, p_variation_id, p_order_id, p_qty, v_new, p_reason)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO NOTHING
  RETURNING id INTO v_mov_id;

  IF v_mov_id IS NULL THEN
    RETURN v_current;  -- reposición ya aplicada → no-op
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = v_new, updated_at = NOW()
   WHERE id = p_variation_id AND tenant_id = p_tenant_id;

  RETURN v_new;
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_restore(UUID, UUID, INTEGER, UUID, TEXT) IS
  'BLOQUE C item 4 — reposición atómica e idempotente de stock (cancelación). Espejo de rpc_stock_decrement. Retorna new_stock.';
