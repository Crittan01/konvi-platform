-- ============================================================================
-- Keep conversations.last_interaction_at in sync with message traffic
-- Date: 2026-04-22
--
-- Why:
--   Inbox list is sorted by conversations.last_interaction_at.
--   Historical data showed stale timestamps because inserts into messages did not
--   update the parent conversation row.
--
-- What this migration does:
--   1) Backfill last_interaction_at from existing messages (max created_at).
--   2) Add trigger to update last_interaction_at on each new message insert.
-- ============================================================================

-- 1) Backfill existing conversations using latest message timestamp.
WITH latest_messages AS (
  SELECT
    m.conversation_id,
    MAX(m.created_at) AS last_message_at
  FROM public.messages m
  GROUP BY m.conversation_id
)
UPDATE public.conversations c
SET last_interaction_at = lm.last_message_at
FROM latest_messages lm
WHERE c.id = lm.conversation_id
  AND c.last_interaction_at IS DISTINCT FROM lm.last_message_at;


-- 2) Trigger function to keep timestamp aligned for new traffic.
CREATE OR REPLACE FUNCTION public.sync_conversation_last_interaction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE public.conversations c
  SET last_interaction_at = GREATEST(c.last_interaction_at, NEW.created_at)
  WHERE c.id = NEW.conversation_id;

  RETURN NEW;
END;
$$;


DROP TRIGGER IF EXISTS trg_sync_conversation_last_interaction ON public.messages;
CREATE TRIGGER trg_sync_conversation_last_interaction
AFTER INSERT ON public.messages
FOR EACH ROW
EXECUTE FUNCTION public.sync_conversation_last_interaction();


COMMENT ON FUNCTION public.sync_conversation_last_interaction IS
  'Updates conversations.last_interaction_at when a new message is inserted.';
