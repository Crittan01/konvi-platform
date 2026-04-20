-- =============================================================================
-- Tabla order_tracking — Tracking de envíos por orden
--
-- Centraliza datos de tracking de cualquier proveedor de logística (MeLi, Envia).
-- MeLi: se llena desde el webhook 'shipments'.
-- Envia: se llenará en Fase 2 al generar etiqueta.
-- =============================================================================

CREATE TABLE public.order_tracking (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID        NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  order_id          UUID        NOT NULL REFERENCES public.orders(id)  ON DELETE CASCADE,
  provider          TEXT        NOT NULL,              -- 'mercadolibre' | 'envia'
  external_id       TEXT,                              -- ID del envío en el proveedor
  status            TEXT,
  tracking_number   TEXT,
  tracking_url      TEXT,
  carrier           TEXT,
  estimated_delivery DATE,
  raw               JSONB,                             -- payload completo del proveedor
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices
CREATE UNIQUE INDEX idx_order_tracking_external
  ON public.order_tracking(tenant_id, provider, external_id)
  WHERE external_id IS NOT NULL;

CREATE INDEX idx_order_tracking_order  ON public.order_tracking(order_id);
CREATE INDEX idx_order_tracking_tenant ON public.order_tracking(tenant_id);

-- RLS
ALTER TABLE public.order_tracking ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation" ON public.order_tracking
  FOR ALL USING (tenant_id = app_current_tenant());

-- Trigger updated_at
CREATE OR REPLACE FUNCTION update_order_tracking_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_order_tracking_updated_at
  BEFORE UPDATE ON public.order_tracking
  FOR EACH ROW EXECUTE FUNCTION update_order_tracking_updated_at();
