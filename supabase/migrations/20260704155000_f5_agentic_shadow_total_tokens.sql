-- F5 bot_engine (decisión #2) — telemetría de costo LLM por tenant.
--
-- NO aplicada aún: pendiente decisión/aplicación founder (ledger tiene drift — ver
-- feedback_supabase_migrations). Migración ADITIVA de bajo riesgo.
--
-- Contexto: `AgenticTurnResult.total_tokens` ya se acumula en el agentic loop
-- (services/ai-orchestrator/agentic/agent.py, suma usage_metadata.total_token_count
-- de todos los responses Gemini del turn). Sin esta columna el insert de audit no
-- puede persistirlo → el código degrada seguro (retry sin la columna, ver
-- dispatcher._persist_turn_audit). Con la columna aplicada, cada turno agentic
-- registra su costo en tokens → insumo directo para pricing/límites por tenant.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

ALTER TABLE public.agentic_shadow_log
  ADD COLUMN IF NOT EXISTS total_tokens INTEGER;

-- Índice parcial para agregaciones de costo por tenant (SUM(total_tokens)
-- WHERE total_tokens IS NOT NULL) sin escanear filas legacy sin dato.
CREATE INDEX IF NOT EXISTS idx_agentic_shadow_total_tokens
  ON public.agentic_shadow_log (tenant_id, created_at DESC)
  WHERE total_tokens IS NOT NULL;

COMMENT ON COLUMN public.agentic_shadow_log.total_tokens IS
  'F5: tokens Gemini consumidos por el turn agentic (prompt + candidates + tools, '
  'via usage_metadata.total_token_count sumado sobre el loop multi-tool). NULL en '
  'filas previas a esta migración. Insumo de costo LLM por tenant.';
