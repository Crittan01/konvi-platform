-- A11 audit (IDOR — Ola 3) — Aislamiento multi-tenant de los RPCs de stock.
--
-- HALLAZGO (verificado en remote pre-check 2026-06-25): los RPCs SECURITY DEFINER
-- `rpc_stock_reservation_consume(p_reservation_id, p_order_id)`,
-- `rpc_stock_reservation_release(p_reservation_id)` y
-- `rpc_stock_reservation_extend(p_reservation_id, p_new_ttl_min)` operan SOLO por
-- `p_reservation_id` sin exigir el tenant del caller. Como corren con privilegios
-- de definer (bypass RLS), un caller que conozca el UUID de una reserva de OTRO
-- tenant podría consumirla/liberarla/extenderla (IDOR cross-tenant sobre stock).
-- `rpc_stock_reserve` YA exige `p_tenant_id` — esta migración alinea las otras 3.
--
-- ESTRATEGIA: expand-contract (la migración no rompe nada).
--   FASE 1 (esta migración) = EXPAND: se AÑADEN overloads con `p_tenant_id` que
--     filtran por tenant (`AND tenant_id = p_tenant_id`). Las firmas viejas
--     COEXISTEN → los callers actuales siguen funcionando sin cambio.
--   FASE 2 (deploy de código posterior) = MIGRATE CALLERS: lib/stock_reservation.py
--     + orders.py + payment_link_tool.py pasan a las firmas de 3 args.
--   FASE 3 (migración ulterior) = CONTRACT: DROP de las firmas viejas sin tenant.
-- NUNCA cambiar la firma in-place (rompería los callers durante la ventana de deploy).
--
-- ADR-0025 (aislamiento multi-tenant = filtro explícito por tenant_id).

-- ── consume con p_tenant_id (overload de 3 args) ─────────────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_consume(
  p_reservation_id UUID,
  p_order_id       UUID,
  p_tenant_id      UUID
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
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

  INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason, order_id)
  VALUES (p_tenant_id, r.variation_id, -r.qty, v_new_stock, 'reservation_consumed', p_order_id);

  UPDATE public.stock_reservations
     SET status = 'consumed', consumed_at = NOW(), order_id = p_order_id, updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id;
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_reservation_consume(UUID, UUID, UUID) IS
  'A11 IDOR fix: consume reserva exigiendo tenant del caller (filtra cross-tenant). Reemplaza a la firma (UUID,UUID) en fase contract.';

-- ── release con p_tenant_id (overload de 2 args) ─────────────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_release(
  p_reservation_id UUID,
  p_tenant_id      UUID
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.stock_reservations
     SET status = 'released', released_at = NOW(), updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active';
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_reservation_release(UUID, UUID) IS
  'A11 IDOR fix: libera reserva exigiendo tenant del caller. Reemplaza a la firma (UUID) en fase contract.';

-- ── extend con p_tenant_id (overload de 3 args) ──────────────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_extend(
  p_reservation_id UUID,
  p_new_ttl_min    INTEGER,
  p_tenant_id      UUID
)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_new TIMESTAMPTZ := NOW() + make_interval(mins => p_new_ttl_min);
BEGIN
  UPDATE public.stock_reservations
     SET expires_at = v_new, updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_extend: reservation_not_active_or_cross_tenant';
  END IF;
  RETURN v_new;
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_reservation_extend(UUID, INTEGER, UUID) IS
  'A11 IDOR fix: extiende TTL exigiendo tenant del caller. Reemplaza a la firma (UUID,INTEGER) en fase contract.';
