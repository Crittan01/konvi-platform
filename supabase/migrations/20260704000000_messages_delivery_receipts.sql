-- Delivery receipts WhatsApp — persistencia del estado real de entrega Meta.
--
-- Contexto: el connector-whatsapp YA parsea `value.statuses[]` (sent | delivered |
-- read | failed) con delivered/read timestamps, pricing y errors[] (parser.py
-- `_parse_status_event`), pero el evento `outbound_status` no tenía handler de
-- persistencia (template_events.handle_event → return None) ni destino en DB.
-- El Inbox pintaba los checks contra `messages.processed` (flag interno del
-- orquestador), NO contra la entrega real de Meta.
--
-- Esta migración agrega a `public.messages` las columnas para almacenar el
-- estado de entrega real por mensaje outbound. El handler
-- `persist_outbound_status` (template_events.py) las llena de forma idempotente
-- y monótona (nunca degrada read→delivered ante reenvíos/reordenamientos de Meta).
--
-- Todas las columnas son NULLABLE: sólo aplican a mensajes outbound trackeados
-- por Meta; inbound e históricos quedan en NULL y el Inbox cae al heurístico
-- previo (processed).
--
-- Realtime: `messages` ya está en la publicación `supabase_realtime` con
-- REPLICA IDENTITY FULL (20260417000000_enable_realtime.sql), por lo que estas
-- columnas viajan en los eventos UPDATE hacia el Inbox sin cambios extra.

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS delivery_status  TEXT,
  ADD COLUMN IF NOT EXISTS delivered_at     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS read_at          TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failed_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS delivery_error   JSONB,
  ADD COLUMN IF NOT EXISTS pricing_category TEXT,
  ADD COLUMN IF NOT EXISTS pricing_billable BOOLEAN;

-- Estados canónicos de entrega Meta (independientes de processing_status, que
-- describe el lado orquestador). NULL permitido para inbound/históricos.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'messages_delivery_status_check'
      AND conrelid = 'public.messages'::regclass
  ) THEN
    ALTER TABLE public.messages DROP CONSTRAINT messages_delivery_status_check;
  END IF;
END
$$;

ALTER TABLE public.messages
  ADD CONSTRAINT messages_delivery_status_check
  CHECK (delivery_status IS NULL
         OR delivery_status IN ('sent', 'delivered', 'read', 'failed'));

COMMENT ON COLUMN public.messages.delivery_status IS
  'Estado de entrega REAL reportado por Meta (value.statuses[].status): sent | delivered | read | failed. NULL = inbound o outbound histórico sin receipt. Distinto de processing_status (lado orquestador).';
COMMENT ON COLUMN public.messages.delivery_error IS
  'errors[] de Meta cuando delivery_status=failed: [{code,title,message}]. Diagnóstico de rechazos asíncronos (número bloqueado, ventana 24h cerrada, plantilla pausada).';
COMMENT ON COLUMN public.messages.pricing_category IS
  'pricing.category de Meta (utility|marketing|authentication|service) — insight de billing por conversación.';

-- Búsqueda por meta_message_id ya cubierta por el UNIQUE existente en
-- messages.meta_message_id (usado como clave de match del receipt).
