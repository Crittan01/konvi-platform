-- Sobreventa silenciosa — el segundo consume de la misma variación no descontaba stock.
--
-- CADENA DE FALLO (es el camino NORMAL del bot, no un borde):
--   1. El cliente agrega un producto → reserva A (qty 1).
--   2. Dice "agregame 2 más" → `cart.py` maneja ese caso creando una SEGUNDA reserva (B, qty 2)
--      para la MISMA variación. El fix F4 de checkout también reserva el delta como fila nueva.
--   3. Pago aprobado → `consume_by_cart` itera las reservas activas del carrito:
--      · Reserva A: UPDATE stock −1 + INSERT en stock_movements → OK.
--      · Reserva B: el UPDATE descuenta −2, pero el INSERT choca con el índice único
--        `uq_stock_movements_order_variation_reason (order_id, variation_id, reason)
--         WHERE order_id IS NOT NULL` → EXCEPTION → **rollback de TODA la RPC**, incluido el
--        descuento de stock.
--   4. El llamador (services/ai-orchestrator/lib/stock_reservation.py) captura la excepción,
--      loguea un warning y CONTINÚA. Nadie comparaba `consumed` contra el total de reservas.
--   → Pedido confirmado, el cliente pagó 3 unidades, el inventario bajó 1. Sobreventa silenciosa.
--
-- FIX — INSERT acumulativo en vez de colisionar:
--   El índice único es CORRECTO (una fila por pedido/variación/motivo; varias filas idénticas
--   serían ambiguas). Lo que estaba mal era asumir que un pedido consume UNA sola reserva por
--   variación. Con ON CONFLICT ... DO UPDATE el ledger ACUMULA el delta en esa única fila:
--   "este pedido consumió N unidades de esta variación", sin importar en cuántas reservas se
--   repartió.
--   La RPC exige `status='active'` con FOR UPDATE, así que una reserva ya consumida no vuelve a
--   entrar: el ON CONFLICT solo acumula reservas DISTINTAS, nunca la misma dos veces.
--
-- BASE: se parte de la definición VIGENTE en prod — la overload de 3 args
-- (20260625120000_stock_rpc_tenant_scoped_expand), que ya scopea TODO por p_tenant_id. Esa
-- defensa cross-tenant se PRESERVA íntegra; el único cambio funcional es el ON CONFLICT.
-- (La overload legacy de 2 args se deja intacta: no se toca lo que no se está arreglando.)
--
-- NO se clampea el stock a 0 (GREATEST): un stock negativo es DIAGNÓSTICO — indica cuánto se
-- sobrevendió y frena ventas nuevas igual. Clampear escondería la magnitud del problema.

CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_consume(
  p_reservation_id uuid,
  p_order_id uuid,
  p_tenant_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
  r RECORD;
  v_new_stock INTEGER;
BEGIN
  SELECT * INTO r FROM public.stock_reservations
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active'
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_consume: reservation_not_active_or_missing_or_cross_tenant';
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = stock_quantity - r.qty,
         updated_at = NOW()
   WHERE id = r.variation_id AND tenant_id = p_tenant_id
   RETURNING stock_quantity INTO v_new_stock;

  -- ON CONFLICT ACUMULATIVO: si este pedido ya consumió otra reserva de la MISMA variación,
  -- se suma el delta a la fila existente del ledger en vez de reventar. Antes, esta colisión
  -- abortaba la transacción y el descuento de stock se perdía → sobreventa silenciosa.
  -- El índice objetivo es PARCIAL, así que el predicado va en la inferencia del ON CONFLICT.
  INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason, order_id)
  VALUES (p_tenant_id, r.variation_id, -r.qty, v_new_stock, 'reservation_consumed', p_order_id)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO UPDATE SET
    delta     = stock_movements.delta - r.qty,
    new_stock = v_new_stock;

  UPDATE public.stock_reservations
     SET status = 'consumed', consumed_at = NOW(), order_id = p_order_id, updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id;
END;
$function$;

-- Norma del proyecto (20260725020000): ninguna función queda expuesta a anon.
REVOKE ALL ON FUNCTION public.rpc_stock_reservation_consume(uuid, uuid, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.rpc_stock_reservation_consume(uuid, uuid, uuid) TO service_role;

COMMENT ON FUNCTION public.rpc_stock_reservation_consume(uuid, uuid, uuid) IS
  'Consume una reserva (scopeada por tenant): descuenta stock y asienta en el ledger. El INSERT es ACUMULATIVO por (order_id, variation_id, reason): un pedido puede consumir VARIAS reservas de la misma variación ("agregame 2 más") y antes la 2ª colisionaba con el índice único, abortaba la transacción y perdía el descuento → sobreventa silenciosa.';
