-- Rev. 109 backlog #2 — Consolidar tenant_agents → ai_agents.
--
-- HONESTIDAD: en la migration 20260608000000 creé una tabla nueva
-- `tenant_agents` sin detectar que `ai_agents` ya existía con UI completa
-- en /dashboard/ai-agents. Esta migration corrige la duplicación:
--   1. Migrar el row default de tenant_agents a ai_agents (con campos nuevos).
--   2. Extender ai_agents con campos faltantes (pitch, tone, role, is_default).
--   3. Drop tenant_agents (vacía excepto Sara Camila ya migrada).
--
-- ai_agents queda como ÚNICA fuente de verdad de la persona del bot
-- per-tenant. La UI existente sigue funcionando + UI nueva extiende pitch/tone.

-- Paso 1: extender ai_agents con campos faltantes (idempotente).
ALTER TABLE ai_agents
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'sales',
  ADD COLUMN IF NOT EXISTS pitch TEXT,
  ADD COLUMN IF NOT EXISTS tone TEXT,
  ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS persona_block TEXT,
  ADD COLUMN IF NOT EXISTS tools_allowed JSONB,
  ADD COLUMN IF NOT EXISTS fsm_states_allowed JSONB;

COMMENT ON COLUMN ai_agents.role IS
  'sales | support | marketing | claims — útil para router pre-LLM futuro.';
COMMENT ON COLUMN ai_agents.pitch IS
  'Pitch corto inyectado al system prompt. Multi-vertical agnóstico. '
  'Ej KAIU: "asesora de KAIU Living Natural, cosmética artesanal". '
  'Ej Tienda Tech: "asesor técnico de Tech X, soluciones de software".';
COMMENT ON COLUMN ai_agents.tone IS
  'Tono conversacional. Default "cordial y profesional, español Colombia".';
COMMENT ON COLUMN ai_agents.is_default IS
  'Solo 1 agente por tenant puede ser default. Si tenant tiene >1 agente, '
  'router pre-LLM elige según intent del cliente.';

-- Paso 2a: si ai_agents YA tiene row para tenants con tenant_agents,
-- actualizar campos pitch/tone/role manteniendo role_description existente.
UPDATE ai_agents aa
SET
  pitch      = COALESCE(ta.pitch, aa.pitch),
  tone       = COALESCE(ta.tone, aa.tone),
  role       = COALESCE(ta.role, aa.role),
  updated_at = NOW()
FROM tenant_agents ta
WHERE ta.tenant_id = aa.tenant_id AND ta.is_default = TRUE;

-- Paso 2b: si tenant tiene row en tenant_agents pero NO en ai_agents,
-- crear el row en ai_agents con todos los campos.
INSERT INTO ai_agents (
  tenant_id, name, role, pitch, tone, is_default,
  role_description, strict_guardrails
)
SELECT
  ta.tenant_id, ta.name, ta.role, ta.pitch, ta.tone, TRUE,
  'Eres el agente de atención al cliente. Te encargas de asistir e informar cordialmente.',
  TRUE
FROM tenant_agents ta
WHERE ta.is_default = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM ai_agents WHERE tenant_id = ta.tenant_id
  );

-- Paso 2c: agregar UNIQUE (tenant_id) WHERE is_default=TRUE en ai_agents
-- para que el upsert de la UI (onConflict: 'tenant_id') sea formal.
CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_tenant_default_unique
  ON ai_agents (tenant_id)
  WHERE is_default = TRUE;

-- Paso 3: drop tenant_agents (datos ya migrados).
DROP TABLE IF EXISTS tenant_agents CASCADE;
