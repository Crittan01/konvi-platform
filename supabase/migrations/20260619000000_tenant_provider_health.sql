-- =============================================================================
-- Rev. 109 J.2.11 — Tenant provider health dashboard (PER-TENANT view)
--
-- Contexto: tenant tiene 5 integraciones (WhatsApp/Wompi/Envia/MeLi/Telegram).
-- Hoy debe entrar a 5 dashboards externos para ver si todo funciona —
-- fricción alta. Este feature centraliza salud en Tenant Console.
--
-- Vista cross-tenant founder = Platform Console (diferido, ver doc 0005).
-- Backend reusable: mismo schema sirve a ambos consoles cuando exista
-- Platform Console.
--
-- Diseño:
--   - tenant_provider_health: 1 fila por (tenant, provider, metric).
--   - UPSERT en cada poll del cron (cada 5min), preserva última observación.
--   - Histórico opcional: tabla aparte tenant_provider_health_history si se
--     necesita (Fase 2 — hoy MVP solo current state).
--   - RLS: tenant ve solo SUS rows; service_role full para cron.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_provider_health (
    tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,
        -- Canónico snake_case: 'whatsapp' | 'wompi' | 'envia' | 'meli' | 'telegram'
    metric        TEXT NOT NULL,
        -- Ejemplos por provider:
        --   whatsapp: 'quality_rating' | 'messaging_limit_tier'
        --   wompi:    'declined_rate_24h'
        --   envia:    'stale_shipments_count'
        --   meli:     'oauth_token_health'
        --   telegram: 'pending_update_count' | 'last_webhook_error'
    value         TEXT,
        -- Stored as text para soportar enums (GREEN/YELLOW/RED, HIGH/MEDIUM/LOW)
        -- + numeric (cast en UI). Evita esquema rígido cuando proveedor cambia.
    threshold     TEXT,
        -- Threshold textual para mostrar contexto en UI (e.g. "<5%", "<3")
    status        TEXT NOT NULL DEFAULT 'unknown',
        -- 'healthy' (green) | 'warning' (yellow) | 'critical' (red) | 'unknown'
    detail        JSONB DEFAULT '{}'::jsonb,
        -- Detalle adicional (raw response, error message, etc.)
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, provider, metric),

    CONSTRAINT tenant_provider_health_provider_valid
        CHECK (provider IN ('whatsapp', 'wompi', 'envia', 'meli', 'telegram', 'aveonline')),

    CONSTRAINT tenant_provider_health_status_valid
        CHECK (status IN ('healthy', 'warning', 'critical', 'unknown'))
);

COMMENT ON TABLE public.tenant_provider_health IS
    'Métricas de salud de las integraciones del tenant. Refrescada por cron '
    'cada 5min. UPSERT con PK (tenant, provider, metric) preserva única fila '
    'por métrica con última observación. Tenant ve via Settings → Salud.';


-- Índice por tenant para list query en Settings (filtro por tenant + sort).
CREATE INDEX IF NOT EXISTS tenant_provider_health_tenant_idx
    ON public.tenant_provider_health (tenant_id, observed_at DESC);

-- Índice por status para alerting global (cron query "todas las RED del sistema").
CREATE INDEX IF NOT EXISTS tenant_provider_health_status_idx
    ON public.tenant_provider_health (status, observed_at DESC)
 WHERE status IN ('warning', 'critical');


-- RLS — tenant ve solo SU data.
ALTER TABLE public.tenant_provider_health ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_provider_health_tenant_select
    ON public.tenant_provider_health;
CREATE POLICY tenant_provider_health_tenant_select
    ON public.tenant_provider_health
    FOR SELECT
    TO authenticated
    USING (
        tenant_id = ((auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid)
    );

-- NO POLICY para INSERT/UPDATE/DELETE — solo service_role escribe (cron worker).


-- ─── RPC: UPSERT métrica con cálculo automático de status ─────────────────

CREATE OR REPLACE FUNCTION public.fn_upsert_provider_health(
    p_tenant_id   UUID,
    p_provider    TEXT,
    p_metric      TEXT,
    p_value       TEXT,
    p_threshold   TEXT DEFAULT NULL,
    p_status      TEXT DEFAULT 'unknown',
    p_detail      JSONB DEFAULT '{}'::jsonb
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.tenant_provider_health (
        tenant_id, provider, metric, value, threshold, status, detail,
        observed_at, updated_at
    ) VALUES (
        p_tenant_id, p_provider, p_metric, p_value, p_threshold, p_status, p_detail,
        NOW(), NOW()
    )
    ON CONFLICT (tenant_id, provider, metric)
    DO UPDATE
       SET value       = EXCLUDED.value,
           threshold   = EXCLUDED.threshold,
           status      = EXCLUDED.status,
           detail      = EXCLUDED.detail,
           observed_at = NOW(),
           updated_at  = NOW();
END;
$$;

COMMENT ON FUNCTION public.fn_upsert_provider_health IS
    'J.2.11 — cron worker invoca esta función para registrar/actualizar métricas '
    'de salud por (tenant, provider, metric). Status determina semáforo UI.';

GRANT EXECUTE ON FUNCTION public.fn_upsert_provider_health TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_upsert_provider_health FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_upsert_provider_health FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_upsert_provider_health FROM anon;


-- ─── RPC: detectar transiciones HEALTHY → WARNING/CRITICAL para alertar ──

CREATE OR REPLACE FUNCTION public.fn_detect_health_degradations(
    p_window_minutes INTEGER DEFAULT 10
)
RETURNS TABLE (
    tenant_id  UUID,
    provider   TEXT,
    metric     TEXT,
    value      TEXT,
    status     TEXT,
    detail     JSONB
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    -- Métricas WARNING/CRITICAL observadas dentro de la ventana (transición reciente).
    -- El worker compara con el snapshot previo en memoria; este RPC es helper
    -- para queries globales del founder (Platform Console futuro).
    SELECT
        tenant_id, provider, metric, value, status, detail
      FROM public.tenant_provider_health
     WHERE status IN ('warning', 'critical')
       AND updated_at > NOW() - (p_window_minutes || ' minutes')::INTERVAL
     ORDER BY status DESC, observed_at DESC;
$$;

COMMENT ON FUNCTION public.fn_detect_health_degradations IS
    'Helper Platform Console — listar todas las degradations recientes '
    'cross-tenant. Hoy NO usado (Tenant Console solo ve su propio data).';

GRANT EXECUTE ON FUNCTION public.fn_detect_health_degradations TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_detect_health_degradations FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_detect_health_degradations FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_detect_health_degradations FROM anon;
