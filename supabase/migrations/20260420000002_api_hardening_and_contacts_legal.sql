-- =============================================================================
-- API Hardening + Contrato Legal extendido de Contactos
-- Fecha: 2026-04-20
-- =============================================================================

-- ── 1) Idempotencia persistente para operaciones write ──────────────────────
CREATE TABLE IF NOT EXISTS public.idempotency_keys (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  idempotency_key  TEXT NOT NULL,
  request_method   TEXT NOT NULL,
  request_path     TEXT NOT NULL,
  request_hash     TEXT NOT NULL,
  response_status  INTEGER,
  response_body    JSONB,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at       TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
  UNIQUE (tenant_id, idempotency_key, request_method, request_path)
);

ALTER TABLE public.idempotency_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.idempotency_keys;
CREATE POLICY "Tenant Isolation" ON public.idempotency_keys
  FOR ALL USING (tenant_id = app_current_tenant());

CREATE OR REPLACE FUNCTION update_idempotency_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_idempotency_keys_updated_at ON public.idempotency_keys;
CREATE TRIGGER set_idempotency_keys_updated_at
  BEFORE UPDATE ON public.idempotency_keys
  FOR EACH ROW EXECUTE FUNCTION update_idempotency_updated_at();

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_tenant_created
  ON public.idempotency_keys (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires_at
  ON public.idempotency_keys (expires_at);

-- ── 2) Contrato legal extendido de contactos (Habeas Data) ──────────────────
ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS consent_source TEXT,
  ADD COLUMN IF NOT EXISTS consent_notice_version TEXT,
  ADD COLUMN IF NOT EXISTS consent_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS consent_actor_email TEXT,
  ADD COLUMN IF NOT EXISTS consent_revoked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS consent_revoked_reason TEXT;

-- Fuentes canónicas de autorización (manual console / canales externos).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'contacts_consent_source_check'
  ) THEN
    ALTER TABLE public.contacts
      ADD CONSTRAINT contacts_consent_source_check
      CHECK (
        consent_source IS NULL OR
        consent_source IN (
          'manual_console',
          'whatsapp',
          'web_form',
          'phone_call',
          'in_person',
          'import',
          'other'
        )
      );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS contacts_consent_revoked_idx
  ON public.contacts (tenant_id, consent_revoked_at);

