-- =============================================================================
-- WhatsApp Outbound Queue (Inbox humano -> cola -> worker -> WhatsApp)
-- Fecha: 2026-04-20
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgmq;

-- Cola durable para envíos outbound de agente humano.
DO $$
BEGIN
  PERFORM pgmq.create('whatsapp_outbound_messages');
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

-- Enqueue helper
CREATE OR REPLACE FUNCTION public.enqueue_whatsapp_outbound_message(
  p_message JSONB,
  p_delay INTEGER DEFAULT 0
)
RETURNS BIGINT
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
  SELECT COALESCE(
    (SELECT msg_id
     FROM pgmq.send(
       'whatsapp_outbound_messages',
       p_message,
       GREATEST(0, p_delay)
     ) AS msg_id
     LIMIT 1),
    0
  );
$$;

-- Dequeue helper
CREATE OR REPLACE FUNCTION public.dequeue_whatsapp_outbound_messages(
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
    'whatsapp_outbound_messages',
    GREATEST(1, p_vt),
    GREATEST(1, p_qty)
  ) AS q;
$$;

-- ACK helper
CREATE OR REPLACE FUNCTION public.ack_whatsapp_outbound_message(
  p_msg_id BIGINT
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
  SELECT pgmq.delete('whatsapp_outbound_messages', p_msg_id);
$$;
