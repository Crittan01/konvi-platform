-- Sem 7 F2 cierre 2026-05-27 — ADR-0018 Fase B shadow mode.
--
-- Tabla append-only para registrar las respuestas que el agentic
-- orchestrator HABRÍA dado, mientras el legacy sigue respondiendo al
-- cliente. Permite comparar comportamiento legacy vs agentic sobre
-- tráfico real SIN impactar al cliente.
--
-- Política retention: 90 días (rolling — pg_cron diario).
--
-- Usado por `services/ai-orchestrator/agentic/dispatcher.py` cuando
-- AGENTIC_SHADOW_ENABLED=true (env var, OFF por default).

CREATE TABLE IF NOT EXISTS public.agentic_shadow_log (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
  message_id UUID,                       -- mensaje inbound que disparó el turn
  inbound_text TEXT,                     -- ≤500 chars (truncated en código)
  agentic_outbound TEXT,                 -- lo que agentic HABRÍA enviado
  tool_calls_executed INTEGER DEFAULT 0,
  tool_call_log JSONB,                   -- audit completo (max 30 calls)
  truncated BOOLEAN DEFAULT FALSE,
  truncated_reason TEXT,
  error TEXT,                            -- si agentic crashed
  elapsed_seconds NUMERIC(10, 3)         -- performance tracking
);

CREATE INDEX IF NOT EXISTS idx_agentic_shadow_tenant_created
  ON public.agentic_shadow_log (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agentic_shadow_conversation
  ON public.agentic_shadow_log (conversation_id, created_at DESC);

-- RLS: lectura solo para tenant propietario + service_role.
ALTER TABLE public.agentic_shadow_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agentic_shadow_log_tenant_isolation ON public.agentic_shadow_log;
CREATE POLICY agentic_shadow_log_tenant_isolation
  ON public.agentic_shadow_log
  FOR SELECT
  USING (tenant_id = public.current_tenant_id());

-- service_role bypass via standard pattern (no policy = service_role
-- accede vía RLS=off por config Supabase).

COMMENT ON TABLE public.agentic_shadow_log IS
  'ADR-0018 Fase B: log silencioso del agentic orchestrator en shadow mode. '
  'Permite comparar respuestas legacy vs agentic sobre tráfico real sin '
  'impactar al cliente. Retention 90d.';

COMMENT ON COLUMN public.agentic_shadow_log.agentic_outbound IS
  'Texto que el agentic HABRÍA enviado al cliente. Legacy es quien '
  'realmente respondió mientras shadow mode esté activo.';
