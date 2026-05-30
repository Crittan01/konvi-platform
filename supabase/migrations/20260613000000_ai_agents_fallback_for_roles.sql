-- Rev. 109 ADR-0017 — fallback_for_roles explícito per agente default.
--
-- CONTEXTO ARQUITECTÓNICO:
-- ────────────────────────
-- Hasta hoy, el router multi-agente (services/ai-orchestrator/agentic/
-- agent_router.py:select_agent_for_inbound) tenía un comportamiento
-- IMPLÍCITO: cuando el role clasificado del inbound NO matcheaba ningún
-- agente especialista, el default atrapaba TODO sin que el operador lo
-- hubiera configurado.
--
-- DECISIÓN (founder 2026-05-28):
-- Hacer el fallback EXPLÍCITO via columna `fallback_for_roles JSONB` en
-- el agente default. Operador desmarca explícitamente lo que NO quiere
-- que el default cubra. Roles no marcados → handoff humano.
--
-- BACKWARD-COMPAT: DEFAULT '["sales","support","marketing","claims"]' =
-- los 4 roles activos. Comportamiento idéntico al previo.

ALTER TABLE ai_agents
  ADD COLUMN IF NOT EXISTS fallback_for_roles JSONB
    NOT NULL
    DEFAULT '["sales","support","marketing","claims"]'::jsonb;

UPDATE ai_agents
SET fallback_for_roles = '["sales","support","marketing","claims"]'::jsonb
WHERE is_default = true AND fallback_for_roles IS NULL;

-- Validador IMMUTABLE: subqueries no van en CHECK, usamos función pura
-- sobre JSONB. Acepta solo los 5 roles canónicos del template
-- (agent_templates.py). Cualquier role fantasma → constraint violation.
CREATE OR REPLACE FUNCTION _ai_agents_fallback_roles_valid(roles JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    elem TEXT;
BEGIN
    IF jsonb_typeof(roles) <> 'array' THEN
        RETURN FALSE;
    END IF;
    FOR elem IN SELECT jsonb_array_elements_text(roles)
    LOOP
        IF elem NOT IN ('sales', 'support', 'marketing', 'claims', 'custom') THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$;

ALTER TABLE ai_agents
  DROP CONSTRAINT IF EXISTS ai_agents_fallback_roles_valid;
ALTER TABLE ai_agents
  ADD CONSTRAINT ai_agents_fallback_roles_valid
  CHECK (_ai_agents_fallback_roles_valid(fallback_for_roles));

COMMENT ON COLUMN ai_agents.fallback_for_roles IS
  'Roles que este agente cubre como fallback cuando no existe agente '
  'especialista. Solo aplica a is_default=true. Roles NO marcados → '
  'handoff humano. Default: 4 roles (backward-compat pre-rev109).';
