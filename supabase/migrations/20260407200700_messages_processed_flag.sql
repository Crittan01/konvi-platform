-- Migración: campo 'processed' en messages para el AI Orchestrator
-- El worker lee mensajes WHERE processed=FALSE AND direction='inbound'
-- y los marca TRUE al completar el ciclo (respuesta enviada por WhatsApp)

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

-- Índice para el poller del Orchestrator (evitar full-scan en tablas grandes)
-- Parcial: solo indexa los mensajes pendientes — máxima eficiencia
CREATE INDEX IF NOT EXISTS idx_messages_inbound_unprocessed
  ON public.messages (tenant_id, created_at ASC)
  WHERE processed = FALSE AND direction = 'inbound';

-- Comentarios de columnas para documentación en Supabase Studio
COMMENT ON COLUMN public.messages.processed IS
  'Flag que el AI Orchestrator setea a TRUE tras enviar la respuesta de WhatsApp';
COMMENT ON COLUMN public.messages.processed_at IS
  'Timestamp UTC en que el Orchestrator procesó este mensaje';
