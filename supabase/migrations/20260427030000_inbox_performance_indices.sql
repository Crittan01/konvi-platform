-- Índices críticos para el Inbox — identificados en auditoría de producción
--
-- Sin estos índices, el Inbox hace full table scan en cada operación:
-- 1. Listar conversaciones por tenant ordenadas por last_interaction_at
-- 2. Cargar mensajes de una conversación ordenados por created_at
-- 3. Deduplicar mensajes por meta_message_id (webhook Meta puede reintentar)

-- Conversaciones: tenant + ordenamiento principal del Inbox
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_last_interaction
  ON public.conversations (tenant_id, last_interaction_at DESC);

-- Mensajes: cargar chat de una conversación (query más frecuente del Inbox)
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
  ON public.messages (conversation_id, created_at DESC);

-- Mensajes: deduplicación rápida por meta_message_id (webhook Meta reintenta)
CREATE INDEX IF NOT EXISTS idx_messages_meta_message_id
  ON public.messages (meta_message_id)
  WHERE meta_message_id IS NOT NULL;
