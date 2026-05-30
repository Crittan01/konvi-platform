-- Rev. 109 founder 2026-05-29 — Notas privadas del operador per conv.
--
-- Backlog P0-1 (docs/refactor/0002-inbox-improvements-backlog.md):
-- el operador necesita dejar memos persistentes per conversación que
-- NO se envían al cliente. Casos de uso:
--   - "Cliente pidió cambio talla la próxima vez."
--   - "Llamada agendada para 2026-06-05 9am."
--   - "Cliente conflictivo histórico — usar tono cordial."
--   - "Promo aplicada manualmente, no re-aplicar."
--
-- Sin esto, el operador pierde contexto entre sesiones.
--
-- DECISIONES ARQUITECTÓNICAS:
--   - Tabla separada `conversation_notes` (no JSONB en conversations) →
--     append-only audit trail + un operador no sobreescribe nota del otro.
--   - RLS por tenant_id (defensa en profundidad + service_role + frontend).
--   - author_user_id NOT NULL — trazabilidad operador que creó la nota.
--   - is_pinned boolean — operador marca nota crítica para que siempre
--     aparezca arriba del thread (ej. "VIP", "cliente conflictivo").
--   - Soft delete via deleted_at — conserva audit trail Habeas Data si
--     el operador "borra" una nota con PII implícita.

CREATE TABLE IF NOT EXISTS public.conversation_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    author_user_id UUID NOT NULL REFERENCES auth.users(id),
    content TEXT NOT NULL CHECK (length(trim(content)) >= 1 AND length(content) <= 2000),
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- Index para lectura típica: por conv ordenado pinned+created desc.
CREATE INDEX IF NOT EXISTS conversation_notes_conv_idx
    ON public.conversation_notes (conversation_id, is_pinned DESC, created_at DESC)
    WHERE deleted_at IS NULL;

-- Index para audit cross-conv del autor (futuro: dashboard "mis notas").
CREATE INDEX IF NOT EXISTS conversation_notes_author_idx
    ON public.conversation_notes (author_user_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- RLS
ALTER TABLE public.conversation_notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversation_notes_tenant_read ON public.conversation_notes;
CREATE POLICY conversation_notes_tenant_read
    ON public.conversation_notes
    FOR SELECT
    USING (
        tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    );

DROP POLICY IF EXISTS conversation_notes_tenant_insert ON public.conversation_notes;
CREATE POLICY conversation_notes_tenant_insert
    ON public.conversation_notes
    FOR INSERT
    WITH CHECK (
        tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
        AND author_user_id = auth.uid()
    );

DROP POLICY IF EXISTS conversation_notes_author_update ON public.conversation_notes;
CREATE POLICY conversation_notes_author_update
    ON public.conversation_notes
    FOR UPDATE
    USING (
        author_user_id = auth.uid()
        OR (
            -- Owners y managers pueden editar/pinear notas de sus operadores.
            tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
            AND (auth.jwt() -> 'app_metadata' ->> 'role') IN ('owner', 'manager')
        )
    );

-- Trigger updated_at automático.
CREATE OR REPLACE FUNCTION public._touch_conversation_notes_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_conversation_notes_updated_at ON public.conversation_notes;
CREATE TRIGGER trg_conversation_notes_updated_at
    BEFORE UPDATE ON public.conversation_notes
    FOR EACH ROW
    EXECUTE FUNCTION public._touch_conversation_notes_updated_at();

COMMENT ON TABLE public.conversation_notes IS
    'Notas privadas del operador per conversación (no enviadas al cliente). '
    'Rev. 109 founder 2026-05-29 — P0-1 backlog. '
    'Append-only effective via soft delete; pin para nota crítica.';
