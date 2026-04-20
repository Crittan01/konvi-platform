-- ============================================================================
-- Mercado Libre OAuth state anti-tamper + anti-replay support table
-- Date: 2026-04-19
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.integration_oauth_states (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  nonce_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT integration_oauth_states_provider_check
    CHECK (provider IN ('mercadolibre')),
  CONSTRAINT integration_oauth_states_nonce_unique
    UNIQUE (provider, nonce_hash)
);

CREATE INDEX IF NOT EXISTS idx_integration_oauth_states_lookup
  ON public.integration_oauth_states (provider, tenant_id, expires_at DESC);

CREATE INDEX IF NOT EXISTS idx_integration_oauth_states_unconsumed
  ON public.integration_oauth_states (provider, consumed_at, expires_at DESC)
  WHERE consumed_at IS NULL;

ALTER TABLE public.integration_oauth_states ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'integration_oauth_states'
      AND policyname = 'Tenant Isolation'
  ) THEN
    CREATE POLICY "Tenant Isolation"
      ON public.integration_oauth_states
      FOR ALL
      USING (tenant_id = app_current_tenant());
  END IF;
END
$$;
