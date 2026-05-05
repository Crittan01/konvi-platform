-- =============================================================================
-- Rev. 104 (F1-10) — review_queue: cola de conversaciones que el LLM no pudo
-- atender (cascade degraded) o que un invariant bloqueó.
--
-- Cierra el loop entre LLM degraded path → operador humano. Sin esto, el
-- cliente recibía un genérico "tuve un problema técnico" y el operador
-- humano no veía contexto del fallo.
--
-- UI: nueva pestaña "Revisión LLM" en Tenant Console / Inbox.
-- Cuando una entry queda atendida, el operador la marca `resolved=true` y
-- la conversation regresa a `bot_active` (o queda en human_takeover si el
-- caso requiere seguimiento).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.review_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    last_message_id UUID,           -- mensaje inbound que disparó el degraded
    fsm_state       TEXT,           -- estado al momento del fallo (CATALOG_MODE, NEEDS_CONSENT, etc.)
    reason          TEXT NOT NULL,  -- 'llm_degraded' | 'invariant_block' | 'manual_escalation'
    error_chain     TEXT,           -- Stack/exc summary cuando reason='llm_degraded'
    prompt_snapshot TEXT,           -- system_prompt en el momento del fallo (truncado)
    priority        SMALLINT NOT NULL DEFAULT 1,  -- 1=normal, 2=alta, 3=crítica
    resolved        BOOLEAN NOT NULL DEFAULT false,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,            -- email del operador que cerró
    resolution_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Lookups frecuentes: por tenant + abiertos, ordenados por prioridad/edad.
CREATE INDEX IF NOT EXISTS review_queue_tenant_open_idx
    ON public.review_queue (tenant_id, resolved, priority DESC, created_at ASC)
    WHERE resolved = false;

-- Lookups por conversation (UI Inbox).
CREATE INDEX IF NOT EXISTS review_queue_conversation_idx
    ON public.review_queue (conversation_id, created_at DESC);

-- RLS: solo el tenant owner ve sus filas.
ALTER TABLE public.review_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS review_queue_tenant_select ON public.review_queue;
CREATE POLICY review_queue_tenant_select ON public.review_queue
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

DROP POLICY IF EXISTS review_queue_tenant_update ON public.review_queue;
CREATE POLICY review_queue_tenant_update ON public.review_queue
    FOR UPDATE
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- service_role bypasea RLS automáticamente (insert/select/update sin restricción).

COMMENT ON TABLE public.review_queue IS
    'Cola de conversaciones que requieren revisión humana (LLM degraded / invariant block / escalation manual). Rev. 104 F1-10.';
COMMENT ON COLUMN public.review_queue.reason IS
    'llm_degraded | invariant_block | manual_escalation';
COMMENT ON COLUMN public.review_queue.priority IS
    '1=normal · 2=alta · 3=crítica (ej. mental_health_crisis)';
