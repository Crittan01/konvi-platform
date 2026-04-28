-- Inbox B2 — Estado intermedio 'ack_pending' para mensajes outbound
--
-- Cuando el worker envía un mensaje a Meta y recibe meta_message_id, debe
-- persistir esa traza en DB. Si el UPDATE en DB falla tras 3 retries, el
-- mensaje queda enviado en Meta pero sin trazabilidad clara. Marcarlo como
-- 'ack_pending' permite identificar y reconciliar manualmente esos casos.
--
-- Estados ahora soportados: pending, processing, processed, skipped, failed,
-- ack_pending.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'messages_processing_status_check'
  ) THEN
    ALTER TABLE public.messages DROP CONSTRAINT messages_processing_status_check;
  END IF;
END$$;

ALTER TABLE public.messages
  ADD CONSTRAINT messages_processing_status_check
  CHECK (processing_status IN ('pending', 'processing', 'processed', 'skipped', 'failed', 'ack_pending'));

COMMENT ON CONSTRAINT messages_processing_status_check ON public.messages IS
  'Estados de procesamiento. ack_pending = enviado a Meta pero DB UPDATE falló (requiere reconciliación).';
