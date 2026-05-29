-- Rev. 109 auditoría arquitectónica — cleanup duplicación ai_agents.
--
-- AUDITORÍA REVELÓ:
-- ─────────────────
-- Migration 20260610000000 extendió ai_agents con pitch + tone, pero estos
-- campos ya existían en tenants como business_pitch + tono_comunicacion
-- (configurados desde Settings → Filosofía del Negocio).
--
-- Resultado: duplicación + 2 lugares para editar el mismo valor + bot
-- usaba ai_agents priorizando sobre tenants → fuente de verdad confusa.
--
-- FIX (separación responsabilidades):
-- ───────────────────────────────────
-- tenants → IDENTIDAD del negocio (qué/por qué + tono de marca):
--   • business_pitch
--   • mision / vision / valores
--   • tono_comunicacion
--
-- ai_agents → COMPORTAMIENTO del bot (cómo actúa):
--   • name (cómo se llama Sara Camila, Andrés, etc.)
--   • role (sales/support/marketing/claims) — multi-agente futuro
--   • role_description (Prompt Maestro)
--   • strict_guardrails
--   • is_default
--   • tools_allowed (futuro multi-agente)
--   • fsm_states_allowed (futuro multi-agente)
--
-- Drop pitch + tone de ai_agents. Tenants vuelve a ser única fuente.

ALTER TABLE ai_agents
  DROP COLUMN IF EXISTS pitch,
  DROP COLUMN IF EXISTS tone;

COMMENT ON TABLE ai_agents IS
  'Comportamiento del bot per tenant. La IDENTIDAD del negocio '
  '(pitch, tono, filosofía) vive en tenants.* — única fuente de verdad. '
  'Aquí solo cómo se llama el agente, su rol funcional, prompt maestro, '
  'y guardrails.';
