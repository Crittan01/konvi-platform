-- Habilita Realtime para las tablas que usan suscripciones en el Inbox.
-- Sin esto, postgres_changes no emite eventos al cliente aunque el canal esté suscrito.
-- Nota: en producción las tablas ya estaban en la publication pero sin REPLICA IDENTITY FULL.
-- El FULL es necesario para que los filtros por columna (conversation_id=eq.xxx) funcionen.
ALTER PUBLICATION supabase_realtime ADD TABLE public.conversations;
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
ALTER TABLE public.messages REPLICA IDENTITY FULL;
ALTER TABLE public.conversations REPLICA IDENTITY FULL;
