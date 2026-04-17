-- Habilita Realtime para las tablas que usan suscripciones en el Inbox.
-- Sin esto, postgres_changes no emite eventos al cliente aunque el canal esté suscrito.
ALTER PUBLICATION supabase_realtime ADD TABLE public.conversations;
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
