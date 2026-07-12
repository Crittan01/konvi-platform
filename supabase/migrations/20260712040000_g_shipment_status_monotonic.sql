-- BLOQUE G (cierre pendiente ADR-0038) — guard monotónico por occurred_at en el
-- status del shipment.
--
-- Problema: fn_record_shipment_tracking_event (20260529000000) actualiza
-- shipments.status con CADA evento nuevo insertado, bloqueando solo estados
-- terminales — NO compara la fecha del evento. Aveonline manda historial sin orden
-- garantizado y puede emitir POSTs concurrentes (dossier §6.2). La ordenación
-- app-layer (F-6/F-7, sort de estado[] por fecha asc) cubre el orden DENTRO de un
-- POST, pero NO entre POSTs concurrentes → un evento VIEJO podía pisar el status
-- fijado por uno más nuevo (regresión entre no-terminales).
--
-- Fix: `shipments.status_occurred_at` (fecha del evento que fijó el status actual)
-- + guard en el UPDATE: solo avanzar si el evento entrante NO es más viejo. Honra
-- el invariante documentado "el status no retrocede". Fail-open si alguna fecha es
-- NULL (no comparable → se permite, como antes).

ALTER TABLE public.shipments
  ADD COLUMN IF NOT EXISTS status_occurred_at TIMESTAMPTZ;

-- Backfill best-effort: la fecha del evento más reciente por shipment (si hay).
UPDATE public.shipments s
   SET status_occurred_at = e.max_occurred
  FROM (
    SELECT shipment_id, MAX(occurred_at) AS max_occurred
    FROM public.shipment_tracking_events
    WHERE shipment_id IS NOT NULL AND occurred_at IS NOT NULL
    GROUP BY shipment_id
  ) e
 WHERE s.id = e.shipment_id
   AND s.status_occurred_at IS NULL;

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

    -- Si insertó (evento nuevo) Y no es terminal → actualizar shipments.status.
    -- ADR-0038: guard monotónico por occurred_at — NO aplicar un evento MÁS VIEJO
    -- que el que fijó el status actual (out-of-order / POSTs concurrentes). También
    -- sella status_occurred_at para la próxima comparación.
    IF v_inserted = 1 AND p_shipment_id IS NOT NULL THEN
        UPDATE public.shipments
        SET status = p_internal_status,
            -- GREATEST (review HIGH): NO bajar/borrar el sello. Un evento con
            -- p_occurred_at NULL no debe wipear status_occurred_at (GREATEST ignora
            -- NULLs en Postgres) — de lo contrario re-abriría la regresión que este
            -- guard cierra (el siguiente evento viejo pasaría el guard NULL).
            status_occurred_at = GREATEST(status_occurred_at, p_occurred_at),
            updated_at = NOW()
        WHERE id = p_shipment_id
          AND tenant_id = p_tenant_id
          AND status NOT IN ('delivered', 'returned', 'cancelled')
          AND (
            status_occurred_at IS NULL
            OR p_occurred_at IS NULL
            OR p_occurred_at >= status_occurred_at
          );
    END IF;

    RETURN (v_inserted = 1);
END;
$$;
