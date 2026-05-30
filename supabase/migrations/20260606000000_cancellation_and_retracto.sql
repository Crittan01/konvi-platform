-- =============================================================================
-- Rev. 109 — Cancelación pedidos + Retracto Ley 1480 de 2011.
-- Fecha: 2026-06-06.
--
-- Implementa el ciclo completo de cancelación/retracto cumpliendo el
-- Estatuto del Consumidor (Ley 1480 de 2011, Art. 47 derecho de retracto).
--
-- 3 tablas:
--   1. order_cancellations  — audit append-only de cancelaciones pre-entrega.
--   2. rma_requests          — solicitudes retracto post-entrega (Art. 47).
--   3. tenant_cancellation_policy — políticas configurables per-tenant.
--
-- Producción-grade:
--   • RLS multi-tenant.
--   • UNIQUE constraints contra duplicados.
--   • Indices para queries operacionales (operador dashboard).
--   • Realtime para Inbox notifications.
--   • CHECK constraints para estados válidos.
-- =============================================================================

-- ── 1. ENUM order cancellation reasons (auditable) ──────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_cancellation_actor') THEN
    CREATE TYPE public.order_cancellation_actor AS ENUM (
      'customer',    -- cliente vía WhatsApp / Inbox
      'operator',    -- agente/manager desde Tenant Console
      'system_auto', -- auto-cancel por TTL expirado, Wompi DECLINED, etc.
      'system_fraud' -- detección automática de patrón sospechoso
    );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_cancellation_status') THEN
    CREATE TYPE public.order_cancellation_status AS ENUM (
      'pending',           -- request creado, pipeline en curso
      'completed',         -- todo ejecutado OK (stock + refund + carriers + notif)
      'partial_failure',   -- algunas acciones OK, otras requieren operador manual
      'failed',            -- falla bloqueante, escalada a operador
      'reversed'           -- cliente arrepentido + dentro de ventana segura
    );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'refund_method_enum') THEN
    CREATE TYPE public.refund_method_enum AS ENUM (
      'wompi_void_auto',     -- void Wompi exitoso pre-settlement
      'wompi_dashboard_manual', -- operador hace refund en dashboard Wompi
      'cod_not_collected',   -- COD nunca recibió $, no aplica refund
      'no_refund_no_payment' -- pending_payment cancelado, nunca hubo $
    );
  END IF;
END $$;


-- ── 2. Tabla order_cancellations (audit append-only) ────────────────────────
CREATE TABLE IF NOT EXISTS public.order_cancellations (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  order_id             UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
  conversation_id      UUID NULL REFERENCES public.conversations(id) ON DELETE SET NULL,
  cancelled_by_actor   public.order_cancellation_actor NOT NULL,
  cancelled_by_user_id UUID NULL,   -- si actor='operator', user_id en auth.users
  status               public.order_cancellation_status NOT NULL DEFAULT 'pending',
  reason_code          TEXT NOT NULL,  -- 'customer_request' | 'stock_fault' | 'fraud' | 'wompi_declined' | etc.
  reason_text          TEXT,           -- texto libre del cliente o operador
  -- Items afectados (cancelación parcial — null = orden completa)
  items_cancelled_json JSONB NULL,
    -- Shape: [{cart_item_id, product_id, variation_id, qty, unit_price_cents}]
    -- NULL = cancelación TOTAL.
  -- Financiero
  amount_refunded_cents BIGINT NOT NULL DEFAULT 0,
  refund_method        public.refund_method_enum NULL,
  refund_txn_id        TEXT NULL,        -- Wompi void txn_id si auto
  refund_status        TEXT NOT NULL DEFAULT 'not_applicable',
    -- 'not_applicable' | 'completed' | 'pending_manual' | 'failed'
  refund_completed_at  TIMESTAMPTZ NULL,
  -- Logística
  shipping_cancelled   BOOLEAN NOT NULL DEFAULT FALSE,
  shipping_cancel_method TEXT NULL,
    -- 'aveonline_api' | 'manual_operator_call' | 'not_applicable' | 'failed'
  shipping_cancel_tracking TEXT NULL,
  -- Stock
  stock_restored       BOOLEAN NOT NULL DEFAULT FALSE,
  stock_restore_method TEXT NULL,
    -- 'reservation_released' | 'stock_movements_reversed' | 'failed'
  -- Notificaciones
  customer_notified_email BOOLEAN NOT NULL DEFAULT FALSE,
  customer_notified_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,
  operator_notified_telegram BOOLEAN NOT NULL DEFAULT FALSE,
  -- Escalación (cuando bot NO ejecuta autónomo)
  escalated_to_operator BOOLEAN NOT NULL DEFAULT FALSE,
  escalation_reason    TEXT NULL,
  -- Audit
  ip_address           INET NULL,
  user_agent           TEXT NULL,
  legal_basis          TEXT NULL,  -- 'ley_1480_art_47' | 'tos_section_X' | etc.
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at         TIMESTAMPTZ NULL,
  -- Append-only: NO se permite UPDATE a campos críticos post-completed.
  -- Solo extensión: updated_at + completed_at + refund_* + customer_notified_*.
  CHECK (
    (status = 'completed' AND completed_at IS NOT NULL) OR
    (status != 'completed')
  )
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_order_cancellations_tenant
  ON public.order_cancellations (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_cancellations_order
  ON public.order_cancellations (order_id);
CREATE INDEX IF NOT EXISTS idx_order_cancellations_status
  ON public.order_cancellations (tenant_id, status)
  WHERE status IN ('pending', 'partial_failure');
CREATE INDEX IF NOT EXISTS idx_order_cancellations_refund_pending
  ON public.order_cancellations (tenant_id, refund_status)
  WHERE refund_status = 'pending_manual';

-- Trigger updated_at
DROP TRIGGER IF EXISTS trg_order_cancellations_updated_at ON public.order_cancellations;
CREATE TRIGGER trg_order_cancellations_updated_at
BEFORE UPDATE ON public.order_cancellations
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- RLS multi-tenant
ALTER TABLE public.order_cancellations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Tenant Isolation" ON public.order_cancellations;
CREATE POLICY "Tenant Isolation" ON public.order_cancellations
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

-- Realtime (Inbox notifications operador)
ALTER PUBLICATION supabase_realtime ADD TABLE public.order_cancellations;
ALTER TABLE public.order_cancellations REPLICA IDENTITY FULL;

COMMENT ON TABLE public.order_cancellations IS
'Audit append-only de cancelaciones de orden PRE-entrega. Cumple Ley 1480 Art. 47 + SIC compliance. Inmutable post-completed (los UPDATEs solo extienden campos no-críticos).';


-- ── 3. Tabla rma_requests (Retracto Ley 1480 Art. 47 — post-entrega) ────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rma_status_enum') THEN
    CREATE TYPE public.rma_status_enum AS ENUM (
      'pending_return',     -- cliente solicitó, debe devolver producto
      'return_in_transit',  -- cliente envió, en camino al tenant
      'received_inspection', -- tenant recibió, validando estado
      'approved_refunding', -- producto OK, refund en curso
      'refund_completed',   -- $ devuelto
      'rejected_product_damaged', -- producto vino dañado/usado, no aplica retracto
      'rejected_out_of_window',   -- fuera de 5 días hábiles, no aplica retracto
      'rejected_excluded_product', -- cosmética abierta, perecederos, personalizados
      'cancelled_by_customer'      -- cliente se arrepintió del retracto
    );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.rma_requests (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  order_id             UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
  conversation_id      UUID NULL REFERENCES public.conversations(id) ON DELETE SET NULL,
  contact_id           UUID NULL REFERENCES public.contacts(id) ON DELETE SET NULL,
  status               public.rma_status_enum NOT NULL DEFAULT 'pending_return',
  -- Window legal: 5 días hábiles desde delivered_at (Art. 47).
  delivered_at         TIMESTAMPTZ NOT NULL,
  retracto_deadline    TIMESTAMPTZ NOT NULL,  -- delivered + 5 días hábiles
  initiated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  initiated_by_actor   public.order_cancellation_actor NOT NULL,
  initiated_by_user_id UUID NULL,
  reason_code          TEXT NOT NULL,  -- 'retracto_art_47' | 'producto_defectuoso' | 'no_satisfecho' | etc.
  reason_text          TEXT,
  -- Items en retracto (parcial — solo algunos items del pedido)
  items_json           JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- [{cart_item_id, product_id, variation_id, qty, unit_price_cents, reason_item}]
  -- Refund (ley 30 días calendario máximo)
  refund_amount_cents  BIGINT NOT NULL DEFAULT 0,
  refund_method        public.refund_method_enum NULL,
  refund_legal_deadline TIMESTAMPTZ NOT NULL,  -- initiated + 30 días calendario
  refund_completed_at  TIMESTAMPTZ NULL,
  refund_txn_id        TEXT NULL,
  -- Logística retorno
  return_label_url     TEXT NULL,    -- etiqueta para que cliente devuelva
  return_carrier       TEXT NULL,
  return_tracking      TEXT NULL,
  return_paid_by       TEXT NOT NULL DEFAULT 'customer',
    -- 'customer' (default ley) | 'tenant' (política tenant más generosa)
  -- Inspección producto al recibir
  product_received_at  TIMESTAMPTZ NULL,
  product_condition    TEXT NULL,   -- 'mismas_condiciones' | 'usado' | 'danado'
  inspected_by_user_id UUID NULL,
  inspection_notes     TEXT NULL,
  -- Notif
  customer_notified_email BOOLEAN NOT NULL DEFAULT FALSE,
  customer_notified_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,
  operator_notified_telegram BOOLEAN NOT NULL DEFAULT FALSE,
  -- Audit
  legal_basis          TEXT NOT NULL DEFAULT 'ley_1480_art_47',
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rma_requests_tenant_status
  ON public.rma_requests (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_rma_requests_order
  ON public.rma_requests (order_id);
CREATE INDEX IF NOT EXISTS idx_rma_requests_deadline
  ON public.rma_requests (refund_legal_deadline)
  WHERE status NOT IN ('refund_completed', 'rejected_product_damaged',
                       'rejected_out_of_window', 'rejected_excluded_product',
                       'cancelled_by_customer');

DROP TRIGGER IF EXISTS trg_rma_requests_updated_at ON public.rma_requests;
CREATE TRIGGER trg_rma_requests_updated_at
BEFORE UPDATE ON public.rma_requests
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

ALTER TABLE public.rma_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Tenant Isolation" ON public.rma_requests;
CREATE POLICY "Tenant Isolation" ON public.rma_requests
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

ALTER PUBLICATION supabase_realtime ADD TABLE public.rma_requests;
ALTER TABLE public.rma_requests REPLICA IDENTITY FULL;

COMMENT ON TABLE public.rma_requests IS
'Retracto post-entrega bajo Ley 1480 Art. 47 (5 días hábiles desde entrega, refund 30 días calendario máximo). Multi-step lifecycle: pending_return → return_in_transit → received_inspection → approved_refunding → refund_completed. Posibles rejected paths cuando producto no aplica retracto.';


-- ── 4. Tabla tenant_cancellation_policy (configurable per-tenant) ────────────
CREATE TABLE IF NOT EXISTS public.tenant_cancellation_policy (
  tenant_id            UUID PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
  -- Política temporal
  allow_cancel_after_picked_up BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE = tenant permite cancelar incluso si courier ya recogió (raro, e.g.
    -- agreement especial con carrier). Default FALSE = solo hasta picked_up.
  -- Política refund
  auto_void_card_window_hours  INTEGER NOT NULL DEFAULT 23,
    -- Cuántas horas post-pago se intenta void Wompi auto (CARD only).
    -- Después, refund manual operador.
  manual_refund_legal_days     INTEGER NOT NULL DEFAULT 30,
    -- Plazo legal Ley 1480 Art. 49 para reintegro (default 30 días).
  -- Política parcial
  allow_partial_cancellation   BOOLEAN NOT NULL DEFAULT TRUE,
    -- Producción real lo soporta. FALSE = solo cancelaciones totales.
  -- Política retracto Art. 47
  enable_retracto_flow         BOOLEAN NOT NULL DEFAULT TRUE,
    -- Si el tenant tiene productos NO sujetos a retracto (cosmética abierta,
    -- perecederos), igual el flow está habilitado pero rechaza producto-a-
    -- producto.
  retracto_window_business_days INTEGER NOT NULL DEFAULT 5,
    -- Default Ley 1480: 5 días hábiles. Tenant puede ser más generoso (e.g.
    -- 15 días). NUNCA menos de 5 (compliance legal).
  retracto_return_paid_by      TEXT NOT NULL DEFAULT 'customer',
    -- 'customer' (default ley) | 'tenant' (más generoso, marketing).
  -- Productos excluidos del retracto (lista de product_ids JSONB).
  retracto_excluded_product_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- E.g. cosmética abierta de KAIU. Aviso al cliente debe ser claro.
  retracto_excluded_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- E.g. ['cosmetica_abierta', 'perecederos', 'personalizados']
  -- Políticas de escalación
  high_value_escalation_threshold_cents BIGINT NOT NULL DEFAULT 50000000,
    -- $500.000 default. Cancel > monto = escala operador (no auto).
  escalate_card_voids BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE = aun con CARD <24h, escalar a operador (tenants risk-averse).
  -- Audit
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- Constraints
  CHECK (retracto_window_business_days >= 5),  -- Ley 1480 mínimo.
  CHECK (manual_refund_legal_days >= 30),       -- Ley 1480 máximo.
  CHECK (retracto_return_paid_by IN ('customer', 'tenant'))
);

DROP TRIGGER IF EXISTS trg_tenant_cancellation_policy_updated_at
  ON public.tenant_cancellation_policy;
CREATE TRIGGER trg_tenant_cancellation_policy_updated_at
BEFORE UPDATE ON public.tenant_cancellation_policy
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

ALTER TABLE public.tenant_cancellation_policy ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenant_cancellation_policy;
CREATE POLICY "Tenant Isolation" ON public.tenant_cancellation_policy
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

COMMENT ON TABLE public.tenant_cancellation_policy IS
'Política de cancelación + retracto configurable por tenant. Defaults cumplen Ley 1480. CHECK constraints garantizan que tenant NO puede ser más estricto que la ley (5 días hábiles retracto mín, 30 días refund máx).';


-- ── 5. Seed default policy para tenants existentes ──────────────────────────
INSERT INTO public.tenant_cancellation_policy (tenant_id)
SELECT id FROM public.tenants
ON CONFLICT (tenant_id) DO NOTHING;


-- ── 6. KAIU: cosmética abierta NO aplica retracto Art. 47 parágrafo ─────────
-- Productos íntimos/higiene personal abiertos están excluidos por ley.
-- Aplicamos a KAIU específicamente.
UPDATE public.tenant_cancellation_policy
SET retracto_excluded_categories = '["cosmetica_abierta", "perecederos"]'::jsonb,
    updated_at = NOW()
WHERE tenant_id = (
  SELECT id FROM public.tenants
  WHERE LOWER(name) LIKE '%kaiu%'
  LIMIT 1
);


-- ── 7. orders.cancelled_at column si no existe ───────────────────────────────
ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS cancelled_by_actor public.order_cancellation_actor NULL,
  ADD COLUMN IF NOT EXISTS cancellation_id UUID NULL REFERENCES public.order_cancellations(id);

CREATE INDEX IF NOT EXISTS idx_orders_cancelled
  ON public.orders (tenant_id, cancelled_at DESC)
  WHERE cancelled_at IS NOT NULL;
