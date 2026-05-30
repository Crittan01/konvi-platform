-- =============================================================================
-- Rev. 105 (Sem 4, H.2.3) — shipments.last_polled_at: timestamp de la última
-- consulta backup polling a Envia /ship/generaltrack/.
--
-- Disparador: dossier Envia 2026-05-05 sec. 6 P0 — webhooks at-least-once
-- sin garantía documentada. El cron poll_pending_shipments necesita saber
-- cuándo fue la última consulta para no duplicar work y respetar SLA Envia
-- (no martillar la API).
--
-- NULL = nunca se ha polled (típico shipment recién creado).
-- =============================================================================

ALTER TABLE public.shipments
    ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ;

-- Índice parcial para query del cron: shipments en estados no-terminales,
-- creados últimos 30 días, no polled recientemente.
-- (last_polled_at IS NULL OR last_polled_at < NOW() - 6h) → query usa index.
CREATE INDEX IF NOT EXISTS shipments_polling_candidate_idx
    ON public.shipments (last_polled_at)
    WHERE status IN ('labeled', 'picked_up', 'in_transit');

COMMENT ON COLUMN public.shipments.last_polled_at IS
    'Timestamp última consulta Envia /ship/generaltrack/ por cron polling. '
    'NULL = nunca polled. Rev. 105 Sem 4 H.2.3.';
