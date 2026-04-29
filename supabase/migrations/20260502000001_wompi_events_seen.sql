-- =============================================================================
-- Wompi events_seen — deduplicación de webhooks duplicados.
-- Fecha: 2026-05-02
--
-- Wompi puede entregar el mismo evento múltiples veces tras retries de su
-- lado cuando nuestro endpoint responde no-2xx o timeout. Para evitar
-- procesar la misma transacción dos veces (decremento doble de stock,
-- doble notificación al cliente), persistimos los `event.id` que ya
-- procesamos exitosamente y descartamos duplicados.
--
-- Refs:
--   https://docs.wompi.co/docs/colombia/eventos/
--   Auditoría agentes 2026-04-29 (Wompi reintenta hasta resolver 2xx;
--   no documenta tabla de retry, mitigación obligatoria del lado merchant).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.wompi_events_seen (
  -- Identificador único del evento Wompi. La doc no expone formalmente
  -- `event.id` siempre — fallback al checksum del signature como hash.
  -- Formato típico: UUID v4 ó SHA256 hex de 64 chars.
  event_id        TEXT PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  -- Para diagnóstico/auditoría
  event_type      TEXT NOT NULL,             -- transaction.updated, nequi_token.updated, etc.
  transaction_id  TEXT,                      -- payload.data.transaction.id si presente
  reference       TEXT,                      -- payload.data.transaction.reference
  status          TEXT,                      -- payload.data.transaction.status
  received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at    TIMESTAMPTZ                -- NULL hasta que el handler termine OK
);

CREATE INDEX IF NOT EXISTS idx_wompi_events_tenant_received
  ON public.wompi_events_seen (tenant_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_wompi_events_transaction
  ON public.wompi_events_seen (transaction_id) WHERE transaction_id IS NOT NULL;

ALTER TABLE public.wompi_events_seen ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.wompi_events_seen;
CREATE POLICY "Tenant Isolation" ON public.wompi_events_seen
  FOR ALL USING (tenant_id = public.app_current_tenant())
  WITH CHECK (tenant_id = public.app_current_tenant());

COMMENT ON TABLE public.wompi_events_seen IS
'Idempotencia de webhooks Wompi. Antes de procesar un evento, INSERT con ON CONFLICT DO NOTHING — si el insert falló (event_id ya existía), descartar como duplicado.';
