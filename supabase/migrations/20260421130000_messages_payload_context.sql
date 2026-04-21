-- Migration: messages_payload_context
-- Propósito: almacenar contexto webhook de WhatsApp (reply context, interactive IDs).

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.messages.payload IS
  'Payload contextual del mensaje (context.id/from, interactive/button data, timestamp).';
