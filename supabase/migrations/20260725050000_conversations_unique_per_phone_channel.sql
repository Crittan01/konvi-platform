-- Carrera de conversación duplicada — cierre a nivel de DB.
--
-- Problema: `_upsert_conversation` (services/connector-whatsapp/services/db_persistence.py:148-199)
-- es un READ-THEN-INSERT sin lock, y NO existe constraint único sobre
-- (tenant_id, customer_phone). En WhatsApp lo NORMAL es que el cliente mande 2-3 mensajes
-- seguidos: el connector los procesa en BackgroundTasks concurrentes, ambos hacen el SELECT
-- (no encuentran nada), y ambos INSERTan → DOS conversaciones para el mismo teléfono.
--
-- Consecuencias en cascada (por eso se arregla ANTES que otros bugs: contamina la validación
-- de todo lo demás):
--   · el coalescing del worker agrupa por conversation_id → dos turnos del bot en paralelo,
--     respondiéndose encima;
--   · el carrito, el estado de la FSM y la orden quedan en una conversación y el historial en
--     la otra;
--   · el Inbox muestra dos hilos para el mismo cliente;
--   · una escalación a humano silencia solo una de las dos.
--
-- La migración 20260428000003_archive_orphan_conversations.sql reconoce POR ESCRITO que ya
-- hubo duplicados en el pasado — o sea, no es teórico.
--
-- ALCANCE DEL ÍNDICE — por qué (tenant_id, customer_phone, channel) y NO parcial:
--   · Se incluye `channel` porque la tabla ya lo tiene (default 'whatsapp') y están previstos
--     otros canales: el mismo teléfono en WhatsApp y en Telegram son conversaciones distintas.
--   · NO se hace parcial por `archived_at IS NULL` a propósito: el lookup del connector NO
--     filtra archivadas (reutiliza la más reciente sea cual sea su estado), así que un índice
--     total coincide EXACTAMENTE con la semántica que el código ya tiene hoy. Un índice parcial
--     permitiría crear una segunda conversación tras archivar la primera — comportamiento que
--     el código nunca ejercita — y además PostgREST no puede inferir el ON CONFLICT de un índice
--     parcial, lo que obligaría a un camino de reintento más frágil.
--
-- VERIFICADO ANTES DE CREARLO (read-only contra prod): 0 duplicados existentes
-- (`GROUP BY tenant_id, customer_phone HAVING count(*) > 1` → vacío), así que el índice se crea
-- sin necesidad de limpieza previa.
--
-- El fix de código (INSERT con manejo de la violación única, para que el request que pierde la
-- carrera reutilice la conversación ganadora en vez de reventar) va en el mismo PR.

CREATE UNIQUE INDEX IF NOT EXISTS conversations_tenant_phone_channel_uniq
  ON public.conversations (tenant_id, customer_phone, channel);

COMMENT ON INDEX public.conversations_tenant_phone_channel_uniq IS
  'Impide conversaciones duplicadas para el mismo (tenant, teléfono, canal). Cierra la carrera del read-then-insert del connector cuando el cliente manda varios mensajes seguidos, que partía carrito/FSM/escalación en silencio.';
