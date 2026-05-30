-- =============================================================================
-- Rev. 108 — shipment_tracking_events: bitácora append-only de cambios de
-- estado físico del envío reportados por el courier (Aveonline webhook
-- §6.2, Envia tracking, MeLi shipments).
--
-- Objetivo: tener verdad observable del envío después de generar la guía.
-- Hoy el sistema marca `shipments.status='labeled'|'simulated'` post
-- Aveonline `generarGuia2` (admin-state). El courier reporta estados
-- físicos (EN RUTA, ENTREGADA, NOVEDAD) que hoy NO persistimos.
--
-- Decisión arquitectónica:
--   • shipments.status sigue siendo el estado canónico actual (denormalized).
--   • shipment_tracking_events almacena CADA cambio reportado (forensics +
--     audit + retry).
--   • Dedup por (provider, external_event_id) UNIQUE — at-least-once safe.
--
-- Refs:
--   docs/research/aveonline-dossier.md §6.2 (webhookEstadosGuias).
--   .context/06-contracts.md §17 (cart-as-SoT events parallel).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.shipment_tracking_events (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    shipment_id        UUID REFERENCES public.shipments(id) ON DELETE CASCADE,
    order_id           UUID REFERENCES public.orders(id) ON DELETE SET NULL,
    provider           TEXT NOT NULL,
        -- 'aveonline' | 'envia' | 'mercadolibre'
    external_event_id  TEXT NOT NULL,
        -- Hash del evento del provider. Aveonline = "{guia}|{estado_id}|{fecha}".
        -- Envia = "{shipmentId}|{type}|{timestamp}". MeLi = "{resource}|{sent_at}".
    raw_status         TEXT,
        -- 'EN RUTA', 'ENTREGADA', 'EN NOVEDAD', 'DEVUELTA' (Aveonline).
    raw_estado_id      INTEGER,
        -- Aveonline numeric estado_id (12=ENTREGADA, etc.).
    internal_status    TEXT NOT NULL,
        -- Mapping canónico: 'in_transit' | 'delivered' | 'exception' |
        -- 'returned' | 'cancelled' | 'pending'.
    description        TEXT,
        -- Descripción humana opcional del courier.
    occurred_at        TIMESTAMPTZ,
        -- Fecha del evento físico según provider (NULL si no provista).
    received_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        -- Cuándo llegó a NUESTRO webhook.
    raw                JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Payload completo del provider (forensics + debugging).

    CONSTRAINT shipment_tracking_events_uniq
        UNIQUE (provider, external_event_id)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS shipment_tracking_events_shipment_idx
    ON public.shipment_tracking_events (shipment_id, received_at DESC)
    WHERE shipment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS shipment_tracking_events_order_idx
    ON public.shipment_tracking_events (order_id, received_at DESC)
    WHERE order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS shipment_tracking_events_tenant_idx
    ON public.shipment_tracking_events (tenant_id, received_at DESC);

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.shipment_tracking_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shipment_tracking_events_tenant_isolation
    ON public.shipment_tracking_events;
CREATE POLICY shipment_tracking_events_tenant_isolation
    ON public.shipment_tracking_events
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT solo vía service_role (handler webhook). Tenant lee via SELECT.

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.shipment_tracking_events IS
    'Bitácora append-only de cambios físicos del envío reportados por '
    'courier webhook. Dedup por (provider, external_event_id). '
    'Rev. 108 — diseño cross-provider (Aveonline + Envia + MeLi).';

COMMENT ON COLUMN public.shipment_tracking_events.internal_status IS
    'Mapping canónico cross-provider: '
    'in_transit|delivered|exception|returned|cancelled|pending. '
    'Provider raw values mapeados en application layer.';

COMMENT ON COLUMN public.shipment_tracking_events.external_event_id IS
    'Identificador único del evento del provider. Garantiza idempotencia '
    'at-least-once. Aveonline composite: guia|estado_id|fecha.';

-- ─── Función helper: insertar evento + actualizar shipments.status ──────────
-- Atómica: dedup + insert evento + update shipment status si es más reciente.
-- Retorna TRUE si insertó nuevo evento, FALSE si era duplicado.

CREATE OR REPLACE FUNCTION public.fn_record_shipment_tracking_event(
    p_tenant_id          UUID,
    p_shipment_id        UUID,
    p_order_id           UUID,
    p_provider           TEXT,
    p_external_event_id  TEXT,
    p_raw_status         TEXT,
    p_raw_estado_id      INTEGER,
    p_internal_status    TEXT,
    p_description        TEXT,
    p_occurred_at        TIMESTAMPTZ,
    p_raw                JSONB
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    INSERT INTO public.shipment_tracking_events (
        tenant_id, shipment_id, order_id, provider,
        external_event_id, raw_status, raw_estado_id,
        internal_status, description, occurred_at, raw
    ) VALUES (
        p_tenant_id, p_shipment_id, p_order_id, p_provider,
        p_external_event_id, p_raw_status, p_raw_estado_id,
        p_internal_status, p_description, p_occurred_at,
        COALESCE(p_raw, '{}'::jsonb)
    )
    ON CONFLICT (provider, external_event_id) DO NOTHING;

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    -- Si insertó (nuevo evento) Y es estado terminal/relevante, actualizar
    -- shipments.status. NO retroceder estados (delivered → in_transit NO).
    IF v_inserted = 1 AND p_shipment_id IS NOT NULL THEN
        UPDATE public.shipments
        SET status = p_internal_status,
            updated_at = NOW()
        WHERE id = p_shipment_id
          AND tenant_id = p_tenant_id
          AND status NOT IN ('delivered', 'returned', 'cancelled');
        -- Skip update si shipment ya está en estado terminal.
    END IF;

    RETURN (v_inserted = 1);
END;
$$;

GRANT EXECUTE ON FUNCTION public.fn_record_shipment_tracking_event
    TO authenticated, service_role;

COMMENT ON FUNCTION public.fn_record_shipment_tracking_event IS
    'Atómico: dedup + insert evento + actualizar shipments.status si nuevo '
    'evento y shipment no en terminal. Retorna TRUE si insertado, FALSE si '
    'duplicado. Idempotente, at-least-once safe.';
