-- ============================================================================
-- Rev. 71 — bot_source_log: append-only por interacción del bot
-- ============================================================================
-- INTERVENCION HUMANA REQUERIDA: aplicar manualmente con
--   supabase db query --linked -f supabase/migrations/20260501000001_bot_source_log.sql
--
-- Propósito: trazabilidad operativa. Cada respuesta del orchestrator inserta
-- un registro con qué fuentes consumió: bloques inyectados al system prompt
-- (catálogo / KB / customer context / sedes / identidad / after-hours), KB
-- categorías recuperadas, FSM state, tokens estimados.
--
-- Este log permite responder "¿el bot está usando realmente mi KB? ¿qué
-- categorías?" sin abrir cada conversación. Auditable vía SQL del Tenant
-- Console (UI elaborada queda para iteración futura — D3 híbrido).
--
-- TTL: 30 días automático vía cleanup periódico (worker.py).
-- Sin PII: solo metadata estructural; el contenido completo queda en messages.
-- ============================================================================

CREATE TABLE IF NOT EXISTS bot_source_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  message_id      UUID REFERENCES messages(id) ON DELETE SET NULL,
  fsm_state       TEXT,
  -- Bloques inyectados al system prompt (true/false por bloque):
  injected_catalog          BOOLEAN NOT NULL DEFAULT false,
  injected_kb               BOOLEAN NOT NULL DEFAULT false,
  injected_store_info       BOOLEAN NOT NULL DEFAULT false,
  injected_business_identity BOOLEAN NOT NULL DEFAULT false,  -- NIT/email/teléfono
  injected_customer_context BOOLEAN NOT NULL DEFAULT false,
  injected_cart_recovery    BOOLEAN NOT NULL DEFAULT false,
  injected_after_hours      BOOLEAN NOT NULL DEFAULT false,
  -- Métricas KB:
  kb_categories_used        TEXT[]  NOT NULL DEFAULT ARRAY[]::TEXT[],   -- ej. {pagos,envios}
  kb_missing_categories     TEXT[]  NOT NULL DEFAULT ARRAY[]::TEXT[],   -- categorías triggered pero sin docs
  kb_docs_count             INTEGER NOT NULL DEFAULT 0,
  -- Métricas catálogo:
  catalog_products_count    INTEGER NOT NULL DEFAULT 0,
  -- Tokens estimados (rough, char-based):
  prompt_chars              INTEGER NOT NULL DEFAULT 0,
  -- Resultado:
  intent_detected           TEXT,
  requires_human            BOOLEAN NOT NULL DEFAULT false,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_source_log_tenant_created
  ON bot_source_log (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bot_source_log_conversation
  ON bot_source_log (conversation_id, created_at DESC);

-- Multi-tenant RLS
ALTER TABLE bot_source_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_source_log_tenant_isolation ON bot_source_log;
CREATE POLICY bot_source_log_tenant_isolation ON bot_source_log
  FOR ALL
  USING (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
  WITH CHECK (tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid);

-- Cleanup helper: borra registros >30 días.
CREATE OR REPLACE FUNCTION cleanup_expired_bot_source_log(retention_days INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM bot_source_log
  WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE bot_source_log IS
  'Rev. 71 — Trazabilidad por mensaje: qué fuentes consumió el bot. '
  'Append-only, TTL 30d, RLS por tenant. Sin PII.';
