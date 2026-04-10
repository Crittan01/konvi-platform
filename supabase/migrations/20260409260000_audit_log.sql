-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: audit_log
-- Registro de acciones por usuario dentro del tenant.
-- Fase 11 — Auditoría.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  user_email  TEXT,                        -- snapshot del email al momento de la acción
  action      TEXT NOT NULL,               -- ej: 'order.status_changed', 'product.created'
  entity_type TEXT NOT NULL,               -- ej: 'order', 'product', 'contact', 'kb_document'
  entity_id   TEXT,                        -- UUID o referencia al recurso afectado
  payload     JSONB,                       -- detalle del cambio (before/after, params, etc.)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_audit_log"
  ON public.audit_log
  FOR ALL
  USING (tenant_id = app_current_tenant());

-- Índices
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant  ON public.audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user    ON public.audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity  ON public.audit_log(tenant_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON public.audit_log(created_at DESC);
