-- =============================================================================
-- Track 6 / Gemini — telemetría de uso desagregada (fase 0 del ahorro por caching)
-- Fecha: 2026-08-22 · Origen: matriz Track 6 (ai.google.dev/gemini-api/docs/caching
-- + /tokens, fetch live 2026-08-22)
--
-- La auditoría del bot ASUMIÓ el ahorro por context caching; la doc oficial NO lo
-- garantiza para gemini-3.1-flash-lite (la tabla de mínimos de implicit caching
-- omite todos los Lite). Decisión correcta: MEDIR primero. Estas columnas
-- desagregan usage_metadata (prompt/cached/thoughts) por turno para responder con
-- datos propios: ¿hay implicit caching en flash-lite? ¿hit rate por estado FSM?
-- Nullable + degrade-safe en el insert (patrón de total_tokens, 20260704155000).
-- =============================================================================

ALTER TABLE public.agentic_shadow_log
  ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER,
  ADD COLUMN IF NOT EXISTS cached_tokens INTEGER,
  ADD COLUMN IF NOT EXISTS thoughts_tokens INTEGER;

COMMENT ON COLUMN public.agentic_shadow_log.cached_tokens IS
  'Track 6: usage_metadata.cached_content_token_count acumulado del turn. '
  'Si es 0 de forma sostenida con prefijo estable → flash-lite no participa en '
  'implicit caching → evaluar explicit caching (CachedContent) con el gate empírico '
  'documentado en la matriz Track 6 (mínimo de tokens no publicado en la guía vigente).';
