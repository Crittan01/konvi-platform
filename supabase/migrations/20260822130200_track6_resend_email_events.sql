-- =============================================================================
-- Track 6 / Resend — email_events: inbox durable de eventos del webhook de email
-- Fecha: 2026-08-22 · Origen: matriz Track 6 (resend.com/docs/webhooks +
-- /docs/webhooks/event-types, fetch live 2026-08-22)
-- Tests: tests/dbharness/test_track6_email_events.py + tests/test_resend_webhook.py
--
-- Por qué existe:
-- 1. DEDUP OBLIGATORIO: Resend entrega webhooks AT-LEAST-ONCE (FAQ oficial) y el
--    header `svix-id` es único por evento → UNIQUE(svix_id) + ON CONFLICT descarta
--    re-entregas (reintentos oficiales: 5s, 5m, 30m, 2h, 5h, 10h hasta recibir 200).
-- 2. DURABILIDAD: el payload verificado se persiste ANTES del 200 ACK (mismo patrón
--    W2 de wompi_webhook_inbox) — si el proceso muere tras el ACK, el evento no se
--    pierde: queda para analítica de entregabilidad y reputación del dominio.
-- 3. SUPRESIÓN LOCAL: suppression.added/removed alimenta la verdad que los senders
--    consultan ANTES de llamar a la API (ahorra cuota del free tier 100/día y evita
--    marcar como "enviado" un email que Resend suprimiría con email.suppressed).
-- 4. ROUTING: los senders etiquetan cada envío con tags tenant_id/order_id/template
--    (Track 6, commit e03b46d5); los eventos email.* traen esas tags de vuelta
--    (Record<string,string> en data.tags) → correlación evento↔tenant/pedido.
--    suppression.* NO trae tags (verificado en doc) → tenant por correlación
--    best-effort vía source_id → email_id (ver routers/resend_webhook.py).
--
-- Seguridad: tabla de infra pura — patrón Track 9 M1-M4 (REVOKE a roles de cliente,
-- GRANT a service_role; RLS por tenant como defensa en profundidad). El writer es
-- el API (webhook) y el lector son los senders, ambos con service_role.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.email_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Header svix-id: único por evento (dedup at-least-once, FAQ oficial).
  svix_id      TEXT NOT NULL UNIQUE,
  -- Routing desde tags del envío. Nullable: eventos de emails de plataforma sin
  -- tag tenant y suppression.* sin correlación encontrada quedan con NULL
  -- (visibles solo para service_role — la policy exige tenant_id = app_current_tenant()).
  tenant_id    UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
  -- Sin FK a propósito: es un hint de correlación y la retención legal puede
  -- purgar orders — un FK rompería el insert del evento (→ retry storm de Resend).
  order_id     UUID,
  -- data.email_id del evento (correlación evento↔envío). En suppression.added se
  -- guarda data.source_id (id del email que originó la supresión).
  email_id     TEXT,
  event_type   TEXT NOT NULL,        -- email.bounced, email.complained, suppression.added, ...
  -- Destinatario normalizado en minúsculas: data.to[1] en email.*, data.email en suppression.*.
  recipient    TEXT,
  -- Payload crudo YA verificado (firma svix válida — nunca se persiste sin verificar).
  payload      JSONB NOT NULL,
  -- created_at del evento según Resend: la entrega NO garantiza orden (FAQ oficial),
  -- así que la secuencia temporal real se ordena por esta columna, no por received_at.
  occurred_at  TIMESTAMPTZ,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_events_tenant_received
  ON public.email_events (tenant_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_email_events_email_id
  ON public.email_events (email_id) WHERE email_id IS NOT NULL;

-- Lookup de supresión en senders: último evento suppression.* de la dirección.
CREATE INDEX IF NOT EXISTS idx_email_events_recipient_occurred
  ON public.email_events (recipient, occurred_at DESC);

ALTER TABLE public.email_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.email_events;
CREATE POLICY "Tenant Isolation" ON public.email_events
  FOR ALL USING (tenant_id = public.app_current_tenant())
  WITH CHECK (tenant_id = public.app_current_tenant());

-- Track 9 (patrón M1-M4): tabla de infra pura → nada a roles de cliente.
REVOKE ALL ON public.email_events FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.email_events TO service_role;

COMMENT ON TABLE public.email_events IS
'Track 6: inbox durable de eventos del webhook Resend (firma svix verificada). Dedup por svix_id (entrega at-least-once). Alimenta analítica de entregabilidad/reputación y la supresión local: los senders consultan el último suppression.added/removed del destinatario antes de enviar (lib/email_suppression.py).';
