-- F7 (auditoría 2026-07-02) — DROP de ai_agents.persona_block (columna muerta: se SELECTea pero nunca
-- se inyecta al prompt; el prompt usa role_description). Autorizado por el founder.
--
-- ⚠️ EXPAND-CONTRACT — NO APLICAR ANTES DEL DEPLOY.
-- get_active_agent (lib/tenant_agents.py) hace un SELECT EXPLÍCITO que incluye persona_block. Si se
-- dropea la columna mientras corre el código viejo, el SELECT falla y get_active_agent DEGRADA
-- silenciosamente TODOS los tenants al agente fallback "Sara Camila" (pierden nombre/rol/persona
-- configurados) hasta el próximo deploy. Por eso:
--   1. El commit que acompaña esta migración YA quitó persona_block del SELECT y del _FALLBACK_AGENT.
--   2. Esta migración se aplica SOLO DESPUÉS de que ese código esté desplegado en prod (el orchestrator
--      es autoDeploy:false → requiere deploy manual). Aplicar antes = regresión de personas de bot.
--
-- INTERVENCION HUMANA REQUERIDA
--   RESPONSABLE: founder/admin.
--   PASOS: (1) desplegar el orchestrator con el código que ya no selecciona persona_block; (2) recién
--     entonces aplicar esta migración (supabase db query --linked -f) + repair + regenerar fixture.
--   CRITERIO DE EXITO: get_active_agent sigue devolviendo el agente real del tenant tras el drop.

ALTER TABLE public.ai_agents DROP COLUMN IF EXISTS persona_block;
