-- Inbox A2 — Badge unread por conversación
--
-- Tabla de lectura por usuario+conversación: cuándo cada operador leyó por
-- última vez una conversación. Permite calcular el conteo de mensajes inbound
-- no leídos sin un campo global en conversations (que no escalaría con
-- múltiples operadores por tenant).
--
-- Modelo:
--   - tenant_id: redundante para RLS rápida y partition key futura.
--   - user_id: id de auth.users del operador.
--   - conversation_id: FK a conversations.
--   - last_read_at: cuándo este operador abrió/marcó como leída la conversación.
-- PK compuesta (tenant_id, user_id, conversation_id) — un registro por operador-conversación.

CREATE TABLE IF NOT EXISTS public.conversation_reads (
  tenant_id        UUID        NOT NULL,
  user_id          UUID        NOT NULL,
  conversation_id  UUID        NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
  last_read_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_reads_tenant_user
  ON public.conversation_reads (tenant_id, user_id);

-- RLS: cada usuario solo ve y modifica sus propios reads dentro de su tenant.
ALTER TABLE public.conversation_reads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user reads own conversation_reads in tenant"
  ON public.conversation_reads
  FOR SELECT
  USING (
    tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    AND user_id = auth.uid()
  );

CREATE POLICY "user upserts own conversation_reads in tenant"
  ON public.conversation_reads
  FOR INSERT
  WITH CHECK (
    tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    AND user_id = auth.uid()
  );

CREATE POLICY "user updates own conversation_reads in tenant"
  ON public.conversation_reads
  FOR UPDATE
  USING (
    tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    AND user_id = auth.uid()
  );

COMMENT ON TABLE public.conversation_reads IS
  'Marca de lectura por operador y conversación. Permite badge unread sin estado global por conversación.';
