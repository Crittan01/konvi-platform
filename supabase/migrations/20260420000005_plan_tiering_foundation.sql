-- =============================================================================
-- Plan Tiering Foundation (Basic / Pro / Enterprise)
-- Fecha: 2026-04-20
-- =============================================================================

-- 1) Catálogo canónico de planes
CREATE TABLE IF NOT EXISTS public.billing_plans (
  plan_code    TEXT PRIMARY KEY CHECK (plan_code IN ('basic', 'pro', 'enterprise')),
  name         TEXT NOT NULL,
  description  TEXT,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order   INTEGER NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.plan_capabilities (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_code      TEXT NOT NULL REFERENCES public.billing_plans(plan_code) ON DELETE CASCADE,
  capability_key TEXT NOT NULL,
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  limit_value    BIGINT,
  period         TEXT NOT NULL DEFAULT 'none' CHECK (period IN ('none', 'minute', 'day', 'month')),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (plan_code, capability_key)
);

-- 2) Suscripción del tenant al plan
CREATE TABLE IF NOT EXISTS public.tenant_subscriptions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  plan_code   TEXT NOT NULL REFERENCES public.billing_plans(plan_code),
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'trialing', 'past_due', 'canceled')),
  started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at    TIMESTAMPTZ,
  meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id)
);

-- 3) Telemetría de uso por capability
CREATE TABLE IF NOT EXISTS public.tenant_usage_counters (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  capability_key TEXT NOT NULL,
  period_start   TIMESTAMPTZ NOT NULL,
  period_end     TIMESTAMPTZ NOT NULL,
  usage_count    BIGINT NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, capability_key, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS public.tenant_usage_events (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  capability_key TEXT NOT NULL,
  units          INTEGER NOT NULL DEFAULT 1 CHECK (units > 0),
  metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4) Índices operativos
CREATE INDEX IF NOT EXISTS idx_plan_capabilities_plan_code
  ON public.plan_capabilities (plan_code);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_counters_lookup
  ON public.tenant_usage_counters (tenant_id, capability_key, period_start DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_events_lookup
  ON public.tenant_usage_events (tenant_id, capability_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_plan_code
  ON public.tenant_subscriptions (plan_code, status);

-- 5) Triggers updated_at
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_billing_plans_updated_at ON public.billing_plans;
CREATE TRIGGER trg_billing_plans_updated_at
BEFORE UPDATE ON public.billing_plans
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_plan_capabilities_updated_at ON public.plan_capabilities;
CREATE TRIGGER trg_plan_capabilities_updated_at
BEFORE UPDATE ON public.plan_capabilities
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_tenant_subscriptions_updated_at ON public.tenant_subscriptions;
CREATE TRIGGER trg_tenant_subscriptions_updated_at
BEFORE UPDATE ON public.tenant_subscriptions
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_tenant_usage_counters_updated_at ON public.tenant_usage_counters;
CREATE TRIGGER trg_tenant_usage_counters_updated_at
BEFORE UPDATE ON public.tenant_usage_counters
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- 6) RLS
ALTER TABLE public.billing_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plan_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_usage_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_usage_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authenticated read billing_plans" ON public.billing_plans;
CREATE POLICY "Authenticated read billing_plans"
  ON public.billing_plans
  FOR SELECT
  USING (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Authenticated read plan_capabilities" ON public.plan_capabilities;
CREATE POLICY "Authenticated read plan_capabilities"
  ON public.plan_capabilities
  FOR SELECT
  USING (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenant_subscriptions;
CREATE POLICY "Tenant Isolation"
  ON public.tenant_subscriptions
  FOR ALL
  USING (tenant_id = app_current_tenant());

DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenant_usage_counters;
CREATE POLICY "Tenant Isolation"
  ON public.tenant_usage_counters
  FOR ALL
  USING (tenant_id = app_current_tenant());

DROP POLICY IF EXISTS "Tenant Isolation" ON public.tenant_usage_events;
CREATE POLICY "Tenant Isolation"
  ON public.tenant_usage_events
  FOR ALL
  USING (tenant_id = app_current_tenant());

-- 7) Seed catálogo de planes
INSERT INTO public.billing_plans (plan_code, name, description, sort_order)
VALUES
  ('basic', 'Basic', 'Plan base para operación inicial.', 10),
  ('pro', 'Pro', 'Plan de crecimiento con mayores cuotas y canales.', 20),
  ('enterprise', 'Enterprise', 'Plan avanzado con capacidades extendidas.', 30)
ON CONFLICT (plan_code) DO UPDATE
SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  sort_order = EXCLUDED.sort_order,
  is_active = TRUE;

-- 8) Seed de capabilities canónicas por plan
WITH caps(plan_code, capability_key, enabled, limit_value, period) AS (
  VALUES
    -- Basic
    ('basic', 'orders.create',            TRUE,  500,  'month'),
    ('basic', 'shipping.quote',           TRUE,  300,  'month'),
    ('basic', 'shipping.confirm_rate',    TRUE,  300,  'month'),
    ('basic', 'conversations.send',       TRUE, 1500,  'month'),
    ('basic', 'integrations.mercadolibre',FALSE, NULL, 'none'),
    ('basic', 'ai.knowledge_base',        TRUE,  NULL, 'none'),
    ('basic', 'ai.agents.configure',      FALSE, NULL, 'none'),
    ('basic', 'analytics.audit.export',   FALSE, NULL, 'none'),
    -- Pro
    ('pro',   'orders.create',            TRUE, 3000,  'month'),
    ('pro',   'shipping.quote',           TRUE, 2000,  'month'),
    ('pro',   'shipping.confirm_rate',    TRUE, 2000,  'month'),
    ('pro',   'conversations.send',       TRUE, 10000, 'month'),
    ('pro',   'integrations.mercadolibre',TRUE, NULL,  'none'),
    ('pro',   'ai.knowledge_base',        TRUE, NULL,  'none'),
    ('pro',   'ai.agents.configure',      TRUE, NULL,  'none'),
    ('pro',   'analytics.audit.export',   TRUE, NULL,  'none'),
    -- Enterprise
    ('enterprise', 'orders.create',            TRUE, NULL, 'none'),
    ('enterprise', 'shipping.quote',           TRUE, NULL, 'none'),
    ('enterprise', 'shipping.confirm_rate',    TRUE, NULL, 'none'),
    ('enterprise', 'conversations.send',       TRUE, NULL, 'none'),
    ('enterprise', 'integrations.mercadolibre',TRUE, NULL, 'none'),
    ('enterprise', 'ai.knowledge_base',        TRUE, NULL, 'none'),
    ('enterprise', 'ai.agents.configure',      TRUE, NULL, 'none'),
    ('enterprise', 'analytics.audit.export',   TRUE, NULL, 'none')
)
INSERT INTO public.plan_capabilities (plan_code, capability_key, enabled, limit_value, period)
SELECT plan_code, capability_key, enabled, limit_value, period
FROM caps
ON CONFLICT (plan_code, capability_key) DO UPDATE
SET
  enabled = EXCLUDED.enabled,
  limit_value = EXCLUDED.limit_value,
  period = EXCLUDED.period;

-- 9) Bootstrapping subscriptions
-- Tenants existentes quedan en enterprise para no romper operación al activar enforcement.
INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status, started_at)
SELECT t.id, 'enterprise', 'active', NOW()
FROM public.tenants t
ON CONFLICT (tenant_id) DO NOTHING;

-- Nuevos tenants nacen en basic (hasta decisión comercial explícita).
CREATE OR REPLACE FUNCTION public.seed_tenant_subscription_default()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status, started_at)
  VALUES (NEW.id, 'basic', 'active', NOW())
  ON CONFLICT (tenant_id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_seed_tenant_subscription_default ON public.tenants;
CREATE TRIGGER trg_seed_tenant_subscription_default
AFTER INSERT ON public.tenants
FOR EACH ROW EXECUTE FUNCTION public.seed_tenant_subscription_default();

-- 10) RPC: consumir capability con cuota (enforcement + telemetría)
CREATE OR REPLACE FUNCTION public.consume_tenant_capability(
  p_tenant_id UUID,
  p_capability_key TEXT,
  p_units INTEGER DEFAULT 1,
  p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
  allowed BOOLEAN,
  plan_code TEXT,
  enabled BOOLEAN,
  limit_value BIGINT,
  period TEXT,
  used BIGINT,
  remaining BIGINT,
  reset_at TIMESTAMPTZ,
  reason TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_now TIMESTAMPTZ := NOW();
  v_plan_code TEXT;
  v_enabled BOOLEAN := TRUE;
  v_limit BIGINT := NULL;
  v_period TEXT := 'none';
  v_period_start TIMESTAMPTZ;
  v_period_end TIMESTAMPTZ;
  v_current_usage BIGINT := 0;
  v_next_usage BIGINT := 0;
BEGIN
  IF p_units IS NULL OR p_units < 1 THEN
    p_units := 1;
  END IF;

  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status, started_at)
  VALUES (p_tenant_id, 'basic', 'active', NOW())
  ON CONFLICT (tenant_id) DO NOTHING;

  SELECT ts.plan_code
  INTO v_plan_code
  FROM public.tenant_subscriptions ts
  WHERE ts.tenant_id = p_tenant_id
  LIMIT 1;

  IF v_plan_code IS NULL THEN
    v_plan_code := 'basic';
  END IF;

  SELECT pc.enabled, pc.limit_value, pc.period
  INTO v_enabled, v_limit, v_period
  FROM public.plan_capabilities pc
  WHERE pc.plan_code = v_plan_code
    AND pc.capability_key = p_capability_key
  LIMIT 1;

  IF NOT FOUND THEN
    -- Fail-open controlado: capability no configurada no bloquea operación.
    v_enabled := TRUE;
    v_limit := NULL;
    v_period := 'none';
  END IF;

  IF COALESCE(v_enabled, TRUE) = FALSE THEN
    RETURN QUERY
    SELECT FALSE, v_plan_code, FALSE, v_limit, v_period, 0::BIGINT, 0::BIGINT, NULL::TIMESTAMPTZ, 'feature_disabled';
    RETURN;
  END IF;

  IF v_period = 'month' THEN
    v_period_start := date_trunc('month', v_now);
    v_period_end := v_period_start + INTERVAL '1 month';
  ELSIF v_period = 'day' THEN
    v_period_start := date_trunc('day', v_now);
    v_period_end := v_period_start + INTERVAL '1 day';
  ELSIF v_period = 'minute' THEN
    v_period_start := date_trunc('minute', v_now);
    v_period_end := v_period_start + INTERVAL '1 minute';
  ELSE
    -- 'none': telemetría mensual para observabilidad
    v_period_start := date_trunc('month', v_now);
    v_period_end := v_period_start + INTERVAL '1 month';
  END IF;

  SELECT uc.usage_count
  INTO v_current_usage
  FROM public.tenant_usage_counters uc
  WHERE uc.tenant_id = p_tenant_id
    AND uc.capability_key = p_capability_key
    AND uc.period_start = v_period_start
    AND uc.period_end = v_period_end
  LIMIT 1;

  v_current_usage := COALESCE(v_current_usage, 0);
  v_next_usage := v_current_usage + p_units;

  IF v_limit IS NOT NULL AND v_period <> 'none' AND v_next_usage > v_limit THEN
    RETURN QUERY
    SELECT
      FALSE,
      v_plan_code,
      TRUE,
      v_limit,
      v_period,
      v_current_usage,
      GREATEST(v_limit - v_current_usage, 0),
      v_period_end,
      'quota_exceeded';
    RETURN;
  END IF;

  INSERT INTO public.tenant_usage_counters (
    tenant_id,
    capability_key,
    period_start,
    period_end,
    usage_count
  )
  VALUES (
    p_tenant_id,
    p_capability_key,
    v_period_start,
    v_period_end,
    p_units
  )
  ON CONFLICT (tenant_id, capability_key, period_start, period_end)
  DO UPDATE SET
    usage_count = public.tenant_usage_counters.usage_count + EXCLUDED.usage_count,
    updated_at = NOW()
  RETURNING usage_count INTO v_next_usage;

  INSERT INTO public.tenant_usage_events (tenant_id, capability_key, units, metadata)
  VALUES (p_tenant_id, p_capability_key, p_units, COALESCE(p_metadata, '{}'::jsonb));

  RETURN QUERY
  SELECT
    TRUE,
    v_plan_code,
    TRUE,
    v_limit,
    v_period,
    v_next_usage,
    CASE WHEN v_limit IS NULL THEN NULL ELSE GREATEST(v_limit - v_next_usage, 0) END,
    v_period_end,
    NULL::TEXT;
END;
$$;

-- 11) RPC: snapshot de capabilities + uso del tenant
CREATE OR REPLACE FUNCTION public.get_tenant_plan_capabilities(
  p_tenant_id UUID
)
RETURNS TABLE (
  plan_code TEXT,
  capability_key TEXT,
  enabled BOOLEAN,
  limit_value BIGINT,
  period TEXT,
  used BIGINT,
  remaining BIGINT,
  reset_at TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  WITH subscription AS (
    SELECT
      COALESCE(
        (SELECT ts.plan_code FROM public.tenant_subscriptions ts WHERE ts.tenant_id = p_tenant_id LIMIT 1),
        'basic'
      ) AS plan_code
  ),
  caps AS (
    SELECT
      s.plan_code,
      pc.capability_key,
      pc.enabled,
      pc.limit_value,
      pc.period,
      CASE
        WHEN pc.period = 'month' THEN date_trunc('month', NOW())
        WHEN pc.period = 'day' THEN date_trunc('day', NOW())
        WHEN pc.period = 'minute' THEN date_trunc('minute', NOW())
        ELSE date_trunc('month', NOW())
      END AS period_start,
      CASE
        WHEN pc.period = 'month' THEN date_trunc('month', NOW()) + INTERVAL '1 month'
        WHEN pc.period = 'day' THEN date_trunc('day', NOW()) + INTERVAL '1 day'
        WHEN pc.period = 'minute' THEN date_trunc('minute', NOW()) + INTERVAL '1 minute'
        ELSE date_trunc('month', NOW()) + INTERVAL '1 month'
      END AS period_end
    FROM subscription s
    JOIN public.plan_capabilities pc ON pc.plan_code = s.plan_code
  )
  SELECT
    c.plan_code,
    c.capability_key,
    c.enabled,
    c.limit_value,
    c.period,
    COALESCE(uc.usage_count, 0) AS used,
    CASE WHEN c.limit_value IS NULL THEN NULL ELSE GREATEST(c.limit_value - COALESCE(uc.usage_count, 0), 0) END AS remaining,
    c.period_end AS reset_at
  FROM caps c
  LEFT JOIN public.tenant_usage_counters uc
    ON uc.tenant_id = p_tenant_id
    AND uc.capability_key = c.capability_key
    AND uc.period_start = c.period_start
    AND uc.period_end = c.period_end
  ORDER BY c.capability_key ASC;
$$;
