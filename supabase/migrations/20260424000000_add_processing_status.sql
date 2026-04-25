-- ============================================================================
-- Add 'processing' to messages processing_status check constraint
-- Date: 2026-04-24
--
-- Reason: worker uses 'processing' as a transient lock state while Gemini
-- responds, to prevent duplicate processing by concurrent workers.
-- ============================================================================

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'messages_processing_status_check'
      AND conrelid = 'public.messages'::regclass
  ) THEN
    ALTER TABLE public.messages DROP CONSTRAINT messages_processing_status_check;
  END IF;
END
$$;

ALTER TABLE public.messages
  ADD CONSTRAINT messages_processing_status_check
  CHECK (processing_status IN ('pending', 'processing', 'processed', 'skipped', 'failed'));

-- Update index to also cover 'processing' (worker queries pending only,
-- but index should remain valid for the filter).
DROP INDEX IF EXISTS idx_messages_inbound_pending;

CREATE INDEX IF NOT EXISTS idx_messages_inbound_pending
  ON public.messages (tenant_id, created_at ASC)
  WHERE direction = 'inbound' AND processing_status IN ('pending', 'processing');

COMMENT ON COLUMN public.messages.processing_status IS
  'Explicit orchestration outcome: pending | processing | processed | skipped | failed';
