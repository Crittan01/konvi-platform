-- Rev. 107 cierre arquitectónico observabilidad agentic.
--
-- Contexto: en cutover (`_run_agentic_full`) el dispatcher NO persistía
-- audit log — solo escribía a stdout via `logger.info`. Cuando los logs
-- rotan (Render Free / VM local) perdemos toda capacidad de diagnóstico
-- runtime (caso conv bde83d84 KAIU 2026-05-23: bot emitió DEGRADED_GENERIC
-- ante input claro y no quedó rastro de finish_reason / tool_call_log).
--
-- Solución: extender `agentic_shadow_log` (creada migración 20260527) con
-- columnas de trazabilidad universal. Renombre semántico — la tabla
-- registra ahora TODOS los turnos agentic (shadow + cutover), no solo
-- shadow. Nombre físico se mantiene por back-compat de queries existentes.
--
-- Columnas nuevas:
--   • `mode TEXT NOT NULL DEFAULT 'shadow'` — distingue paths.
--   • `finish_reason TEXT` — último valor reportado por Gemini en el turn
--     (STOP / MAX_TOKENS / SAFETY / BLOCKLIST / MALFORMED_FUNCTION_CALL /
--     OTHER / UNKNOWN). Permite diagnosticar empty_output sin logs runtime.
--   • `invariant_outcome TEXT` — outcome de la cadena de invariants
--     post-LLM (OK / REWRITE / REJECT / etc.).
--   • `invariant_name TEXT` — nombre del invariant que disparó (si !=OK).
--   • `final_text TEXT` — texto enviado al cliente DESPUÉS de invariants
--     (puede diferir de `agentic_outbound` cuando un invariant reescribe).
--   • `system_prompt_chars INTEGER` — tamaño del system_prompt usado
--     (correlación con saturación de contexto).
--   • `history_turns INTEGER` — turns de history incluidos en messages.

ALTER TABLE public.agentic_shadow_log
  ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'shadow'
    CHECK (mode IN ('shadow', 'cutover')),
  ADD COLUMN IF NOT EXISTS finish_reason TEXT,
  ADD COLUMN IF NOT EXISTS invariant_outcome TEXT,
  ADD COLUMN IF NOT EXISTS invariant_name TEXT,
  ADD COLUMN IF NOT EXISTS final_text TEXT,
  ADD COLUMN IF NOT EXISTS system_prompt_chars INTEGER,
  ADD COLUMN IF NOT EXISTS history_turns INTEGER;

CREATE INDEX IF NOT EXISTS idx_agentic_shadow_mode_created
  ON public.agentic_shadow_log (mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agentic_shadow_finish_reason
  ON public.agentic_shadow_log (finish_reason)
  WHERE finish_reason IS NOT NULL;

COMMENT ON COLUMN public.agentic_shadow_log.mode IS
  'rev. 107: distingue audit shadow (legacy responde, agentic loggea) vs '
  'cutover (agentic responde al cliente). Permite mezclar ambos modes en '
  'una sola tabla y query por mode.';

COMMENT ON COLUMN public.agentic_shadow_log.finish_reason IS
  'rev. 107: último finish_reason de Gemini (STOP/MAX_TOKENS/SAFETY/etc.). '
  'Crítico para diagnosticar empty_output sin depender de logs stdout.';

COMMENT ON COLUMN public.agentic_shadow_log.final_text IS
  'rev. 107: texto enviado al cliente post-invariants. Si difiere de '
  'agentic_outbound, un invariant reescribió la salida del LLM.';
