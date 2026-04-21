-- =============================================================================
-- Human Takeover Notifications Queue (Supabase Queues / pgmq)
-- Fecha: 2026-04-20
-- Objetivo: Desacoplar notificaciones de escalamiento humano con cola durable.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgmq;

-- Crear cola durable (idempotente).
DO $$
BEGIN
  PERFORM pgmq.create('human_takeover_notifications');
EXCEPTION
  WHEN duplicate_table THEN
    NULL;
  WHEN others THEN
    IF POSITION('already exists' IN lower(SQLERRM)) > 0 THEN
      NULL;
    ELSE
      RAISE;
    END IF;
END;
$$;

-- Trigger: cualquier transición a human_takeover en conversations
-- encola un evento para notificación operacional.
CREATE OR REPLACE FUNCTION public.enqueue_human_takeover_notification()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
DECLARE
  payload JSONB;
BEGIN
  IF NEW.tenant_id IS NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.status = 'human_takeover'
     AND OLD.status IS DISTINCT FROM NEW.status THEN
    payload := jsonb_build_object(
      'event_type', 'conversation.human_takeover',
      'tenant_id', NEW.tenant_id,
      'conversation_id', NEW.id,
      'customer_phone', NEW.customer_phone,
      'previous_status', OLD.status,
      'new_status', NEW.status,
      'triggered_at', NOW()
    );

    PERFORM pgmq.send('human_takeover_notifications', payload);
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS conversations_human_takeover_queue_trigger ON public.conversations;
CREATE TRIGGER conversations_human_takeover_queue_trigger
  AFTER UPDATE OF status ON public.conversations
  FOR EACH ROW
  EXECUTE FUNCTION public.enqueue_human_takeover_notification();

-- Wrappers canónicos para consumers de backend (api/orchestrator).
CREATE OR REPLACE FUNCTION public.dequeue_human_takeover_notifications(
  p_vt  INTEGER DEFAULT 90,
  p_qty INTEGER DEFAULT 20
)
RETURNS TABLE (
  msg_id BIGINT,
  read_ct INTEGER,
  enqueued_at TIMESTAMPTZ,
  vt TIMESTAMPTZ,
  message JSONB
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
  SELECT
    q.msg_id,
    q.read_ct,
    q.enqueued_at,
    q.vt,
    q.message
  FROM pgmq.read(
    'human_takeover_notifications',
    GREATEST(1, p_vt),
    GREATEST(1, p_qty)
  ) AS q;
$$;

CREATE OR REPLACE FUNCTION public.ack_human_takeover_notification(
  p_msg_id BIGINT
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
  SELECT pgmq.delete('human_takeover_notifications', p_msg_id);
$$;
