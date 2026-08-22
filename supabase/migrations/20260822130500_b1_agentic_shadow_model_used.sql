-- =============================================================================
-- B-1 / Routing de modelo por estado — agentic_shadow_log.model_used
-- Fecha: 2026-08-22 · Origen: auditoría bot 2026-08-21 §3 ("mismo modelo lite
-- para 'hola' y para el checkout" → routing por estado tras flag de canary)
-- Tests: tests/agentic/test_b1_model_routing.py
--
-- Telemetría del routing por estado (AGENTIC_STATE_ROUTING_ENABLED): el modelo
-- REAL que respondió cada turno (primary o fallback de la cascada). Con el
-- canary en STG se mide: distribución lite/flash por estado, latencia p50/p95
-- por modelo y costo incremental del tier transaccional (3.5-flash = 6× lite)
-- antes de decidir el default. Nullable + degrade-safe en el insert (patrón de
-- total_tokens 20260704155000 y del breakdown Track 6 20260822130100).
-- =============================================================================

ALTER TABLE public.agentic_shadow_log
  ADD COLUMN IF NOT EXISTS model_used TEXT;

COMMENT ON COLUMN public.agentic_shadow_log.model_used IS
  'B-1: modelo Gemini real que respondió el turno (primary o fallback de la cascada). '
  'Telemetría del routing por estado (AGENTIC_STATE_ROUTING_ENABLED): distribución '
  'lite/flash por estado FSM + latencia/costo por modelo para la decisión del default.';
