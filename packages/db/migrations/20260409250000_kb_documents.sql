-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: kb_documents
-- Base de conocimiento por tenant para contexto del AI Orchestrator.
-- Fase 11 — Knowledge Base.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.kb_documents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  content     TEXT NOT NULL,
  category    TEXT NOT NULL DEFAULT 'general',
  -- Categorías sugeridas: faq, politica, negocio, producto, general
  is_active   BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS
ALTER TABLE public.kb_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_kb_documents"
  ON public.kb_documents
  FOR ALL
  USING (tenant_id = app_current_tenant());

-- Índices
CREATE INDEX IF NOT EXISTS idx_kb_documents_tenant   ON public.kb_documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_active   ON public.kb_documents(tenant_id, is_active);

-- Trigger updated_at
CREATE OR REPLACE FUNCTION update_kb_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

CREATE TRIGGER kb_documents_updated_at
  BEFORE UPDATE ON public.kb_documents
  FOR EACH ROW EXECUTE FUNCTION update_kb_updated_at();
