-- ============================================================================
-- Wompi Payments — Fase C
-- Date: 2026-04-24
--
-- 1. Agrega 'pending_payment' como estado válido de orders
-- 2. Crea tabla 'payments' para trazar intentos de pago por pedido
-- ============================================================================

-- ── 1. Anotación de estado pending_payment ───────────────────────────────────
-- orders.status es TEXT sin CHECK constraint en la tabla base.
-- pending_payment se agrega al catálogo válido en código Python (VALID_STATUSES).
-- Esta migración documenta el nuevo estado y agrega comentario a la columna.
COMMENT ON COLUMN public.orders.status IS
  'Estados válidos: pending | pending_payment | confirmed | processing | shipped | delivered | cancelled';

-- ── 2. Tabla payments ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    order_id            UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL DEFAULT 'wompi',
    wompi_link_id       TEXT,
    wompi_txn_id        TEXT,
    checkout_url        TEXT,
    amount_in_cents     BIGINT NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'COP',
    status              TEXT NOT NULL DEFAULT 'pending',
    -- pending | approved | declined | voided | error | expired
    wompi_status        TEXT,
    raw_webhook         JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices operativos
CREATE INDEX IF NOT EXISTS idx_payments_tenant_order
    ON public.payments(tenant_id, order_id);

CREATE INDEX IF NOT EXISTS idx_payments_wompi_link
    ON public.payments(wompi_link_id)
    WHERE wompi_link_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payments_wompi_txn
    ON public.payments(wompi_txn_id)
    WHERE wompi_txn_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payments_status
    ON public.payments(tenant_id, status);

-- ── 3. RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;

-- Lectura: solo el tenant dueño (vía anon/authenticated)
CREATE POLICY "tenant_payments_select" ON public.payments
    FOR SELECT USING (tenant_id = (
        SELECT (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    ));

-- Escritura: solo service_role (backend). Sin política INSERT/UPDATE/DELETE
-- para roles de usuario — toda escritura va por API Gateway con service_role.
