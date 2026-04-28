-- Inbox F1 — Archivar conversaciones huérfanas
--
-- Tras el fix de _upsert_conversation que selecciona la más reciente por
-- last_interaction_at, las conversaciones antiguas duplicadas (mismo
-- tenant_id+phone) quedan huérfanas: ya no reciben mensajes pero ocupan
-- la lista lateral del Inbox y suman al filtrado.
--
-- Modelo:
--   - Columna nueva `archived_at` en conversations.
--   - Se marcan archived_at=now() las conversaciones cerradas sin actividad
--     reciente (>90 días).
--   - Index parcial para queries del Inbox que filtran archived_at IS NULL
--     (los queries activos del lateral).

ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Index parcial: aceleran lista lateral del Inbox (que filtra activas).
DROP INDEX IF EXISTS idx_conversations_tenant_active_last_interaction;
CREATE INDEX idx_conversations_tenant_active_last_interaction
  ON public.conversations (tenant_id, last_interaction_at DESC)
  WHERE archived_at IS NULL;

-- Backfill: archiva conversaciones cerradas sin actividad reciente.
-- Solo si NO han recibido mensajes en los últimos 90 días.
UPDATE public.conversations c
SET archived_at = now()
WHERE c.archived_at IS NULL
  AND c.status = 'closed'
  AND c.last_interaction_at < now() - INTERVAL '90 days'
  AND NOT EXISTS (
    SELECT 1 FROM public.messages m
    WHERE m.conversation_id = c.id
      AND m.created_at >= now() - INTERVAL '90 days'
  );

COMMENT ON COLUMN public.conversations.archived_at IS
  'Marca de archivado. NULL = activa o cerrada reciente; not null = oculta del Inbox por defecto.';
