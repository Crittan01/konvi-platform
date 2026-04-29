-- =============================================================================
-- Stock Reservations — soft-reserve pattern (alineado con Stripe Checkout).
-- Fecha: 2026-05-02
--
-- Reserva temporal de inventario al confirmar el cliente intención de compra
-- (post-quote_shipping). TTL 35 min, alineado con PENDING_PAYMENT_TTL_MINUTES.
-- Cleanup defensivo: filtro `expires_at > NOW()` en el cálculo de "available"
-- garantiza correctness aún si pg_cron no corre.
--
-- Decisiones documentadas en .context/06-contracts.md (sección 17).
-- Refs:
--   https://docs.stripe.com/payments/checkout/managing-limited-inventory
--   https://www.postgresql.org/docs/current/explicit-locking.html (FOR NO KEY UPDATE)
--   https://github.com/citusdata/pg_cron
-- =============================================================================

-- ── 1. ENUM de estado ────────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'stock_reservation_status') THEN
    CREATE TYPE public.stock_reservation_status AS ENUM (
      'active',     -- vigente, descuenta de "available"
      'consumed',   -- pago confirmado → se materializó en stock_movements
      'released',   -- liberada manualmente o por cancelación de pedido
      'expired'     -- TTL vencido sin pago
    );
  END IF;
END
$$;


-- ── 2. Tabla principal ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.stock_reservations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  variation_id    UUID NOT NULL REFERENCES public.product_variations(id) ON DELETE CASCADE,
  -- warehouse_id NULL hoy (single-warehouse-per-tenant). Reservado para multi-bodega.
  warehouse_id    UUID NULL,
  cart_id         UUID NULL REFERENCES public.conversation_carts(id) ON DELETE CASCADE,
  conversation_id UUID NULL REFERENCES public.conversations(id) ON DELETE SET NULL,
  order_id        UUID NULL REFERENCES public.orders(id) ON DELETE SET NULL,
  qty             INTEGER NOT NULL CHECK (qty > 0),
  status          public.stock_reservation_status NOT NULL DEFAULT 'active',
  expires_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  consumed_at     TIMESTAMPTZ NULL,
  released_at     TIMESTAMPTZ NULL,
  CHECK (
    (status = 'consumed' AND consumed_at IS NOT NULL) OR
    (status IN ('released','expired') AND released_at IS NOT NULL) OR
    (status = 'active' AND consumed_at IS NULL AND released_at IS NULL)
  )
);


-- ── 3. Índices ───────────────────────────────────────────────────────────────
-- Crítico: cálculo de "available" filtra por (variation_id, status='active', expires_at > NOW())
CREATE INDEX IF NOT EXISTS idx_stock_res_active
  ON public.stock_reservations (variation_id, expires_at)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_stock_res_tenant
  ON public.stock_reservations (tenant_id);

CREATE INDEX IF NOT EXISTS idx_stock_res_cart
  ON public.stock_reservations (cart_id) WHERE cart_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_stock_res_order
  ON public.stock_reservations (order_id) WHERE order_id IS NOT NULL;

-- Para el barrido pg_cron: solo filas activas con TTL vencido.
CREATE INDEX IF NOT EXISTS idx_stock_res_expired_sweep
  ON public.stock_reservations (expires_at) WHERE status = 'active';


-- ── 4. Trigger updated_at ────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_stock_reservations_updated_at ON public.stock_reservations;
CREATE TRIGGER trg_stock_reservations_updated_at
BEFORE UPDATE ON public.stock_reservations
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();


-- ── 5. RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE public.stock_reservations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.stock_reservations;
CREATE POLICY "Tenant Isolation" ON public.stock_reservations
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());


-- ── 6. Helper: stock disponible considerando reservas activas ────────────────
CREATE OR REPLACE FUNCTION public.fn_variation_available_stock(p_variation_id UUID)
RETURNS INTEGER
LANGUAGE sql STABLE
AS $$
  SELECT GREATEST(
    COALESCE(pv.stock_quantity, 0)
    - COALESCE((
        SELECT SUM(sr.qty)
        FROM public.stock_reservations sr
        WHERE sr.variation_id = pv.id
          AND sr.status = 'active'
          AND sr.expires_at > NOW()
      ), 0),
    0
  )::INTEGER
  FROM public.product_variations pv
  WHERE pv.id = p_variation_id;
$$;

COMMENT ON FUNCTION public.fn_variation_available_stock IS
'Stock disponible = stock_quantity - SUM(active_reservations.qty con TTL vivo). Filtro defensivo expires_at > NOW() asegura correctness aún sin cleanup periódico.';


-- ── 7. RPC: reservar stock atómicamente ──────────────────────────────────────
DROP FUNCTION IF EXISTS public.rpc_stock_reserve(UUID, UUID, INTEGER, UUID, UUID, INTEGER);

CREATE OR REPLACE FUNCTION public.rpc_stock_reserve(
  p_tenant_id       UUID,
  p_variation_id    UUID,
  p_qty             INTEGER,
  p_cart_id         UUID,
  p_conversation_id UUID,
  p_ttl_minutes     INTEGER DEFAULT 35
)
RETURNS TABLE (
  out_reservation_id UUID,
  out_expires_at     TIMESTAMPTZ,
  out_available_after INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current_stock INTEGER;
  v_reserved      INTEGER;
  v_available     INTEGER;
  v_res_id        UUID;
  v_expires       TIMESTAMPTZ;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_reserve: qty must be > 0';
  END IF;

  -- FOR NO KEY UPDATE — bloqueo más débil que FOR UPDATE, suficiente porque
  -- NO modificamos PK/FK de product_variations (solo leemos stock_quantity).
  -- Ref: https://www.postgresql.org/docs/current/explicit-locking.html §13.3.2
  SELECT pv.stock_quantity INTO v_current_stock
  FROM public.product_variations pv
  WHERE pv.id = p_variation_id AND pv.tenant_id = p_tenant_id
  FOR NO KEY UPDATE;

  IF v_current_stock IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_reserve: variation_not_found';
  END IF;

  SELECT COALESCE(SUM(qty), 0) INTO v_reserved
  FROM public.stock_reservations
  WHERE variation_id = p_variation_id
    AND status = 'active'
    AND expires_at > NOW();

  v_available := v_current_stock - v_reserved;

  IF v_available < p_qty THEN
    RAISE EXCEPTION 'rpc_stock_reserve: insufficient_stock'
      USING ERRCODE = 'P0001',
            DETAIL = format('available=%s requested=%s', v_available, p_qty);
  END IF;

  v_expires := NOW() + make_interval(mins => p_ttl_minutes);

  INSERT INTO public.stock_reservations
    (tenant_id, variation_id, cart_id, conversation_id, qty, expires_at)
  VALUES
    (p_tenant_id, p_variation_id, p_cart_id, p_conversation_id, p_qty, v_expires)
  RETURNING id INTO v_res_id;

  RETURN QUERY SELECT v_res_id, v_expires, (v_available - p_qty);
END;
$$;

COMMENT ON FUNCTION public.rpc_stock_reserve IS
'Atómico: SELECT FOR NO KEY UPDATE + check de disponibilidad + INSERT reserva. Levanta SQLSTATE P0001 con DETAIL si stock insuficiente.';


-- ── 8. RPC: extender TTL de una reserva ──────────────────────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_extend(
  p_reservation_id UUID,
  p_new_ttl_min    INTEGER DEFAULT 35
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
  WHERE id = p_reservation_id AND status = 'active';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_extend: reservation_not_active';
  END IF;
  RETURN v_new;
END;
$$;


-- ── 9. RPC: consumir reserva (al confirmar pago) ─────────────────────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_consume(
  p_reservation_id UUID,
  p_order_id       UUID
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
   WHERE id = p_reservation_id AND status = 'active'
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_consume: reservation_not_active_or_missing';
  END IF;

  -- Decremento real de stock_quantity con bloqueo
  UPDATE public.product_variations
     SET stock_quantity = stock_quantity - r.qty,
         updated_at = NOW()
   WHERE id = r.variation_id AND tenant_id = r.tenant_id
   RETURNING stock_quantity INTO v_new_stock;

  -- Auditoría: registrar el movimiento
  INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason, order_id)
  VALUES (r.tenant_id, r.variation_id, -r.qty, v_new_stock, 'reservation_consumed', p_order_id);

  UPDATE public.stock_reservations
     SET status = 'consumed', consumed_at = NOW(), order_id = p_order_id, updated_at = NOW()
   WHERE id = p_reservation_id;
END;
$$;


-- ── 10. RPC: liberar reserva (cancelación o expiración explícita) ────────────
CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_release(
  p_reservation_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.stock_reservations
     SET status = 'released', released_at = NOW(), updated_at = NOW()
   WHERE id = p_reservation_id AND status = 'active';
END;
$$;


-- ── 11. Función de barrido para pg_cron ──────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fn_expire_stock_reservations()
RETURNS INTEGER
LANGUAGE sql
AS $$
  WITH upd AS (
    UPDATE public.stock_reservations
       SET status = 'expired', released_at = NOW(), updated_at = NOW()
     WHERE status = 'active' AND expires_at <= NOW()
     RETURNING 1
  )
  SELECT COUNT(*)::INT FROM upd;
$$;

COMMENT ON FUNCTION public.fn_expire_stock_reservations IS
'Barrido periódico (pg_cron cada 60s recomendado). Marca como expired las reservas con TTL vencido. SELECT cron.schedule(''expire_stock_reservations'', ''* * * * *'', $$SELECT public.fn_expire_stock_reservations();$$);';


-- ── 12. Realtime (opcional) ──────────────────────────────────────────────────
-- El Inbox del operador puede querer ver reservas vivas. Patrón consistente
-- con conversation_carts (REPLICA IDENTITY FULL).
ALTER PUBLICATION supabase_realtime ADD TABLE public.stock_reservations;
ALTER TABLE public.stock_reservations REPLICA IDENTITY FULL;


-- ── 13. Documentación ────────────────────────────────────────────────────────
COMMENT ON TABLE public.stock_reservations IS
'Soft-reserve de inventario (Stripe Checkout pattern). Reserva temporal al confirmar intención de compra (post-quote_shipping). TTL 35 min alineado con PENDING_PAYMENT_TTL_MINUTES. Estados: active → (consumed | released | expired). El cálculo de stock disponible se hace via fn_variation_available_stock().';
