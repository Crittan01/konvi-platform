-- =============================================================================
-- W2 (auditoría 2026-07-13) — Durabilidad del webhook Wompi (dinero).
--
-- GAP: wompi_webhook.py hace `background_tasks.add_task(...)` DESPUÉS del 200 ACK.
-- Un crash del proceso (deploy/OOM/kill) entre el ACK y el fin del procesamiento
-- pierde el evento de pago: Wompi NO reintenta un 200, y su API NO ofrece pull
-- por reference/link (solo por transaction_id, que viaja EN el webhook perdido).
-- Resultado: pago recibido pero orden en pending_payment → el sweeper de TTL la
-- cancela a los ~35 min → dinero cobrado sin orden confirmada.
--
-- FIX: inbox transaccional (store-and-forward). El handler persiste el payload
-- CRUDO aquí ANTES del 200 ACK (idempotente por checksum). El worker reconcilia
-- filas `processed_at IS NULL` re-POSTeando a /api/v1/webhooks/wompi (reusa el
-- flujo verificado completo). La idempotencia real de dinero la da la tabla
-- `wompi_events_seen` (dedup por checksum) + el guard de estado terminal de la
-- orden — esta tabla solo garantiza que el payload SOBREVIVA al crash.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.wompi_webhook_inbox (
    -- signature.checksum del payload Wompi = clave de dedup natural (cambia con
    -- cada payload exacto; Wompi no expone un event.id estable documentado).
    checksum     TEXT PRIMARY KEY,
    raw_payload  JSONB NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL hasta que _process_wompi_event completa (éxito o desenlace terminal:
    -- evento ignorado / huérfano / duplicado / no-aprobado). Un crash mid-proceso
    -- deja esto NULL → el worker lo reconcilia.
    processed_at TIMESTAMPTZ,
    -- nº de re-drives del worker (backstop dead-letter: tras N intentos se deja
    -- de reintentar y queda para revisión manual con last_error).
    attempts     INT NOT NULL DEFAULT 0,
    last_error   TEXT
);

-- Poller de reconciliación: barre filas sin procesar por antigüedad.
CREATE INDEX IF NOT EXISTS idx_wompi_inbox_unprocessed
    ON public.wompi_webhook_inbox (received_at)
    WHERE processed_at IS NULL;

-- Infra de webhook (sin tenant_id — el tenant se resuelve DURANTE el proceso):
-- solo service_role (backend) escribe/lee. RLS ON sin policies = deny-all para
-- authenticated/anon; service_role bypasa RLS. Defense-in-depth (ADR-0025).
ALTER TABLE public.wompi_webhook_inbox ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.wompi_webhook_inbox IS
  'W2 durabilidad Wompi: captura durable del payload crudo ANTES del 200 ACK; el worker reconcilia filas processed_at IS NULL re-POSTeando a /api/v1/webhooks/wompi. Idempotencia de dinero = wompi_events_seen (checksum) + guard estado terminal de la orden.';

-- RPC de reconciliación: reclama atómicamente hasta p_limit filas sin procesar,
-- más viejas que p_min_age_seconds y con attempts < p_max_attempts, incrementa
-- attempts y devuelve el payload. FOR UPDATE SKIP LOCKED = seguro aunque corran
-- múltiples instancias del worker (hoy 1; W4 escala). La llama el worker con
-- service_role (bypasa RLS) → SECURITY INVOKER; search_path fijado por higiene.
CREATE OR REPLACE FUNCTION public.claim_wompi_inbox_batch(
    p_limit INT DEFAULT 20,
    p_min_age_seconds INT DEFAULT 120,
    p_max_attempts INT DEFAULT 5
)
RETURNS TABLE (checksum TEXT, raw_payload JSONB, attempts INT)
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
    UPDATE public.wompi_webhook_inbox AS w
    SET attempts = w.attempts + 1
    WHERE w.checksum IN (
        SELECT c.checksum
        FROM public.wompi_webhook_inbox AS c
        WHERE c.processed_at IS NULL
          AND c.received_at < now() - make_interval(secs => p_min_age_seconds)
          AND c.attempts < p_max_attempts
        ORDER BY c.received_at
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING w.checksum, w.raw_payload, w.attempts;
$$;

REVOKE ALL ON FUNCTION public.claim_wompi_inbox_batch(INT, INT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_wompi_inbox_batch(INT, INT, INT) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_wompi_inbox_batch(INT, INT, INT) TO service_role;
