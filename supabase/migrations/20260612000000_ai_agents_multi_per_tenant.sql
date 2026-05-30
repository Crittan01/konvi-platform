-- Rev. 109 ADR-0017 — habilita multi-agente per tenant.
--
-- BUG REVELADO POR UAT LIVE:
-- ──────────────────────────
-- El index legacy `ai_agents_tenant_id_unique UNIQUE(tenant_id)` impedía
-- crear un segundo agente per tenant (constraint violation):
--   duplicate key value violates unique constraint "ai_agents_tenant_id_unique"
--
-- Este index nació cuando `ai_agents` era 1-a-1 con `tenants` (un solo
-- bot per tenant). Pero ADR-0017 define multi-agente per tenant
-- (Ventas, Soporte, Marketing, Reclamos, ...).
--
-- FIX:
-- ────
-- Drop el index legacy. El index parcial `ai_agents_tenant_default_unique`
-- (UNIQUE(tenant_id) WHERE is_default=TRUE) ya garantiza:
--   • Exactamente 1 agente con is_default=TRUE por tenant.
--   • N agentes adicionales con is_default=FALSE permitidos.
--
-- También verificamos que upsert UI (onConflict: 'tenant_id') NO se
-- rompa: el upsert solo lo usa para actualizar el agente default
-- existente. Como el index parcial sigue garantizando 1 default, el
-- upsert sigue siendo único per tenant para is_default=TRUE.

DROP INDEX IF EXISTS ai_agents_tenant_id_unique;

-- Confirmar que el index parcial sigue intacto.
-- Si NO existe (drift), lo recreamos defensivamente.
CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_tenant_default_unique
  ON ai_agents (tenant_id)
  WHERE is_default = TRUE;
