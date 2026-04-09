-- =============================================================================
-- Fase 10 — Tabla shipments
-- Historial de cotizaciones y envíos via Envia.
-- Diseño completo en docs/integrations/courier-envia.md
-- =============================================================================

CREATE TABLE public.shipments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    order_id            UUID REFERENCES public.orders(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'quoted',
    -- quoted → labeled → picked_up → in_transit → delivered | cancelled
    carrier             TEXT,
    service             TEXT,
    origin_address      JSONB NOT NULL,
    destination_address JSONB NOT NULL,
    parcels             JSONB NOT NULL,       -- [{ weight, length, width, height }]
    quote_response      JSONB,               -- respuesta raw de Envia (rates disponibles)
    selected_rate       JSONB,               -- tarifa seleccionada por el tenant
    label_url           TEXT,                -- Fase 2
    tracking_number     TEXT,                -- Fase 2
    tracking_url        TEXT,                -- Fase 2
    envia_shipment_id   TEXT,                -- ID asignado por Envia al generar label
    pickup_id           TEXT,                -- Fase 2
    estimated_delivery  DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.shipments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation" ON public.shipments
    FOR ALL USING (tenant_id = app_current_tenant());

CREATE INDEX idx_shipments_tenant ON public.shipments(tenant_id);
CREATE INDEX idx_shipments_order  ON public.shipments(order_id);
CREATE INDEX idx_shipments_status ON public.shipments(tenant_id, status);
