-- ============================================================================
-- Conversation + Message processing contract hardening
-- Date: 2026-04-19
--
-- Goals:
--   1) Canonical conversation statuses: bot_active | human_takeover | closed
--   2) Safe backfill from legacy statuses
--   3) Explicit message processing outcome to avoid ambiguous processed flag loops
-- ============================================================================

-- ── 1) Normalize conversation status values ──────────────────────────────────
UPDATE public.conversations
SET status = CASE
  WHEN status IN ('bot_active', 'human_takeover', 'closed') THEN status
  WHEN status IN ('active', 'bot') THEN 'bot_active'
  WHEN status IN ('human_handoff') THEN 'human_takeover'
  WHEN status IN ('resolved') THEN 'closed'
  ELSE 'closed'
END
WHERE status IS DISTINCT FROM CASE
  WHEN status IN ('bot_active', 'human_takeover', 'closed') THEN status
  WHEN status IN ('active', 'bot') THEN 'bot_active'
  WHEN status IN ('human_handoff') THEN 'human_takeover'
  WHEN status IN ('resolved') THEN 'closed'
  ELSE 'closed'
END;

ALTER TABLE public.conversations
  ALTER COLUMN status SET DEFAULT 'bot_active';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'conversations_status_check'
      AND conrelid = 'public.conversations'::regclass
  ) THEN
    ALTER TABLE public.conversations DROP CONSTRAINT conversations_status_check;
  END IF;
END
$$;

ALTER TABLE public.conversations
  ADD CONSTRAINT conversations_status_check
  CHECK (status IN ('bot_active', 'human_takeover', 'closed'));

COMMENT ON COLUMN public.conversations.status IS
  'Canonical statuses: bot_active | human_takeover | closed';


-- ── 2) Add explicit processing outcome fields in messages ────────────────────
ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS processing_status TEXT,
  ADD COLUMN IF NOT EXISTS skip_reason TEXT,
  ADD COLUMN IF NOT EXISTS last_error TEXT,
  ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0;

-- Backfill explicit processing_status from historical processed boolean.
UPDATE public.messages
SET processing_status = CASE
  WHEN direction = 'outbound' THEN 'processed'
  WHEN COALESCE(processed, FALSE) THEN 'processed'
  ELSE 'pending'
END
WHERE processing_status IS NULL
   OR processing_status = '';

-- Enforce supported processing statuses.
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
  ALTER COLUMN processing_status SET DEFAULT 'pending',
  ALTER COLUMN processing_status SET NOT NULL;

ALTER TABLE public.messages
  ADD CONSTRAINT messages_processing_status_check
  CHECK (processing_status IN ('pending', 'processed', 'skipped', 'failed'));

-- Keep legacy processed boolean coherent with explicit status.
UPDATE public.messages
SET processed = (processing_status <> 'pending')
WHERE processed IS DISTINCT FROM (processing_status <> 'pending');

-- Keep timestamp aligned when message is no longer pending.
UPDATE public.messages
SET processed_at = COALESCE(processed_at, NOW())
WHERE processing_status <> 'pending' AND processed_at IS NULL;

-- Replace legacy pending index with explicit processing_status index.
DROP INDEX IF EXISTS idx_messages_inbound_unprocessed;

CREATE INDEX IF NOT EXISTS idx_messages_inbound_pending
  ON public.messages (tenant_id, created_at ASC)
  WHERE direction = 'inbound' AND processing_status = 'pending';

COMMENT ON COLUMN public.messages.processing_status IS
  'Explicit orchestration outcome: pending | processed | skipped | failed';

COMMENT ON COLUMN public.messages.skip_reason IS
  'Reason when processing_status=skipped (e.g. human_takeover_active, closed_conversation, non_text_requires_human)';

COMMENT ON COLUMN public.messages.last_error IS
  'Last orchestration error when processing_status=failed or pending retry';

COMMENT ON COLUMN public.messages.processing_attempts IS
  'Number of orchestration attempts for this inbound message';
