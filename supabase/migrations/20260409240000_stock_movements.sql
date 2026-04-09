-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: stock_movements
-- Historial de ajustes de inventario por variante de producto.
-- Fase 11 — Inventario.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stock_movements (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  product_id    UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
  variation_id  UUID NOT NULL REFERENCES public.product_variations(id) ON DELETE CASCADE,
  delta         INTEGER NOT NULL,           -- positivo = entrada, negativo = salida
  new_stock     INTEGER NOT NULL,           -- stock resultante después del movimiento
  reason        TEXT,                       -- "ajuste manual", "venta", "devolución", etc.
  created_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS
ALTER TABLE public.stock_movements ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_stock_movements"
  ON public.stock_movements
  FOR ALL
  USING (tenant_id = app_current_tenant());

-- Índices
CREATE INDEX IF NOT EXISTS idx_stock_movements_tenant    ON public.stock_movements(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_variation ON public.stock_movements(variation_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_created   ON public.stock_movements(created_at DESC);
