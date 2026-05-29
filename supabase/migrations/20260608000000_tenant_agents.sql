-- Rev. 109 backlog #2 — Multi-agente per-tenant (Plan I.5).
--
-- PROBLEMA QUE RESUELVE:
-- ─────────────────────
-- Hoy `agent_name` está hardcoded a "Sara Camila" + pitch genérico
-- de cosmética. Esto NO escala a:
--   • Tenant tecnología (necesita pitch tech, no cosmética)
--   • Tenant comida (pitch gastronómico)
--   • Multi-agente por tenant: Ventas (Sara), Soporte (Andrés),
--     Marketing (Camila), Reclamos
--
-- DISEÑO MULTI-TENANT + MULTI-AGENTE:
-- ────────────────────────────────────
-- Tabla `tenant_agents` con un row por agente del tenant. Cada agente
-- tiene su persona/pitch/tone + opcionales subsets de tools/states.
-- Backward-compat: si el tenant NO tiene rows, fallback a "Sara Camila"
-- + pitch genérico de cosmética.
--
-- ROUTING (futuro):
-- ─────────────────
-- Hoy solo se usa el agente con is_default=true. Router pre-LLM
-- futuro (Plan I.5.6) clasificará el inbound y elegirá agente:
--   "quiero comprar" → Ventas
--   "cuándo llega mi pedido?" → Soporte
--   "el producto está dañado" → Reclamos
-- Pero arquitectura ya lista para extensión sin tocar schema.

CREATE TABLE IF NOT EXISTS tenant_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Identidad del agente (qué le dirá el bot al cliente).
    name TEXT NOT NULL,
    -- Rol funcional. Útil para router pre-LLM futuro + métricas.
    role TEXT NOT NULL DEFAULT 'sales',  -- sales | support | marketing | claims

    -- Pitch corto inyectado en el system prompt:
    --   KAIU:    "asesora de KAIU Living Natural, cosmética artesanal"
    --   Tech X:  "asesor técnico de Tech X, soluciones de software"
    --   Comida Y: "asesora gastronómica de Comida Y, productos frescos"
    pitch TEXT,
    -- Estilo conversacional. Default "cordial y profesional, español CO".
    tone TEXT,

    -- Override completo del system prompt (NULL = usar default builder).
    -- Solo para casos avanzados (tenant enterprise con prompt custom).
    system_prompt_override TEXT,

    -- Bloque persona extra ("Soy madre, conozco el cuidado natural...").
    -- NULL = sin bloque adicional.
    persona_block TEXT,

    -- Subsets opcionales — NULL = todas las tools/states permitidos.
    -- JSONB arrays para flexibilidad:
    --   ['list_catalog', 'add_to_cart', 'generate_payment_link']
    tools_allowed JSONB,
    fsm_states_allowed JSONB,

    -- Solo 1 agente puede ser is_default=true per tenant.
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_by UUID,  -- auth.users si es del Tenant Console UI
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Constraint: solo 1 default activo per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS tenant_agents_default_unique
  ON tenant_agents (tenant_id)
  WHERE is_default = TRUE AND is_active = TRUE;

-- Index para query "give me the default agent for this tenant"
CREATE INDEX IF NOT EXISTS tenant_agents_lookup_idx
  ON tenant_agents (tenant_id, is_active)
  WHERE is_active = TRUE;

-- RLS: tenant solo ve sus agentes
ALTER TABLE tenant_agents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_agents_isolation ON tenant_agents;
CREATE POLICY tenant_agents_isolation ON tenant_agents
  FOR ALL
  USING (
    tenant_id IN (
      SELECT tenant_id FROM tenant_memberships
      WHERE user_id = auth.uid()
    )
  );

COMMENT ON TABLE tenant_agents IS
  'Multi-agente per-tenant. Cada agente define persona/pitch/tone propios. '
  'Default agent se usa cuando no hay router específico. Multi-tenant + '
  'multi-vertical agnóstico.';

-- Seed: agente default para tenants existentes (Sara Camila preservada).
-- Si ya hay un row default, SKIP. Si no hay, INSERT.
INSERT INTO tenant_agents (tenant_id, name, role, pitch, tone, is_default)
SELECT
  t.id, 'Sara Camila', 'sales',
  COALESCE(
    NULLIF(t.business_pitch, ''),
    'asesora del negocio, productos artesanales'
  ),
  'cordial y profesional, en español Colombia',
  TRUE
FROM tenants t
WHERE NOT EXISTS (
  SELECT 1 FROM tenant_agents ta
  WHERE ta.tenant_id = t.id AND ta.is_default = TRUE AND ta.is_active = TRUE
);
