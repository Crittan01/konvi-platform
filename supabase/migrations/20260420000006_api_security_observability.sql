-- =============================================================================
-- API Security Observability + Idempotency Cleanup
-- Fecha: 2026-04-20
-- =============================================================================

-- 1) Eventos de seguridad API para observabilidad operativa
CREATE TABLE IF NOT EXISTS public.api_security_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  event_type    TEXT NOT NULL,
  endpoint      TEXT NOT NULL,
  request_method TEXT NOT NULL,
  status_code   INTEGER NOT NULL,
  detail        TEXT,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.api_security_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.api_security_events;
CREATE POLICY "Tenant Isolation" ON public.api_security_events
  FOR ALL USING (tenant_id = app_current_tenant());

CREATE INDEX IF NOT EXISTS idx_api_security_events_tenant_created
  ON public.api_security_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_security_events_tenant_endpoint
  ON public.api_security_events (tenant_id, endpoint, status_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_security_events_type
  ON public.api_security_events (event_type, created_at DESC);

-- 2) Limpieza de llaves de idempotencia expiradas (job-friendly)
CREATE OR REPLACE FUNCTION public.cleanup_expired_idempotency_keys(
  p_limit INTEGER DEFAULT 5000
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_deleted BIGINT := 0;
BEGIN
  WITH doomed AS (
    SELECT id
    FROM public.idempotency_keys
    WHERE expires_at < NOW()
    ORDER BY expires_at ASC
    LIMIT GREATEST(1, p_limit)
  ),
  del AS (
    DELETE FROM public.idempotency_keys k
    USING doomed d
    WHERE k.id = d.id
    RETURNING k.id
  )
  SELECT COUNT(*) INTO v_deleted FROM del;

  RETURN COALESCE(v_deleted, 0);
END;
$$;
