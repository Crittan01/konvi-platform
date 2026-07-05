-- =============================================================================
-- F7 — Dedup persistente de alertas de salud (anti re-spam tras restart).
-- Fecha: 2026-07-04
--
-- Problema: worker.py detecta transiciones healthy→warning/critical con un
-- snapshot EN MEMORIA (self._health_status_snapshot). Tras cada restart/deploy
-- del worker el snapshot arranca vacío → todo provider ya degradado cuenta como
-- transición nueva y RE-ALERTA al operador por Telegram. Ruido que erosiona la
-- confianza en las alertas.
--
-- Solución: estado persistente por (tenant, provider, metric) en tabla propia
-- (NO en tenant_provider_health, que el prune de providers desconectados borra).
-- La RPC fn_claim_health_alert replica EXACTAMENTE la semántica in-memory
-- (alertar solo al pasar de {NULL,healthy,unknown} a {warning,critical}) pero
-- sobrevive reinicios.
--
-- Solo service_role (worker) escribe/lee. Idempotente. NO aplicar aún.
-- worker.py degrada seguro (fallback in-memory) si la RPC/tabla no existe.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.provider_health_alert_dedup (
    tenant_id    UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,
    metric       TEXT NOT NULL,
    last_status  TEXT,
        -- Último status OBSERVADO por el worker (se actualiza cada ciclo).
        -- Replica el snapshot in-memory previo, pero persistente.
    alerted_at   TIMESTAMPTZ,
        -- Timestamp de la última alerta emitida (observabilidad).
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, provider, metric)
);

COMMENT ON TABLE public.provider_health_alert_dedup IS
    'F7 — estado persistente de dedup de alertas de salud por (tenant,provider,'
    'metric). Evita re-spam de Telegram tras restart del worker. Separada de '
    'tenant_provider_health (que el prune borra) para no perder el estado.';

ALTER TABLE public.provider_health_alert_dedup ENABLE ROW LEVEL SECURITY;
-- Sin policies para authenticated/anon: solo service_role (worker) accede.
-- (service_role bypassa RLS; RLS ON sin policy = deny-all para el resto.)


-- ─── RPC: reclamar (claim) una alerta de forma atómica y persistente ─────────
-- Retorna TRUE si el worker DEBE alertar (transición good→bad no notificada),
-- FALSE en caso contrario. Siempre persiste el último status observado.
--
-- Semántica idéntica al snapshot in-memory original:
--   should_alert = (last_status ∈ {NULL,'healthy','unknown'})
--                  AND (p_status ∈ {'warning','critical'})

CREATE OR REPLACE FUNCTION public.fn_claim_health_alert(
    p_tenant_id  UUID,
    p_provider   TEXT,
    p_metric     TEXT,
    p_status     TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_prev   TEXT;
    v_should BOOLEAN;
BEGIN
    SELECT last_status INTO v_prev
      FROM public.provider_health_alert_dedup
     WHERE tenant_id = p_tenant_id
       AND provider  = p_provider
       AND metric    = p_metric
       FOR UPDATE;

    v_should := (v_prev IS NULL OR v_prev IN ('healthy', 'unknown'))
                AND p_status IN ('warning', 'critical');

    INSERT INTO public.provider_health_alert_dedup (
        tenant_id, provider, metric, last_status, alerted_at, updated_at
    ) VALUES (
        p_tenant_id, p_provider, p_metric, p_status,
        CASE WHEN v_should THEN NOW() ELSE NULL END,
        NOW()
    )
    ON CONFLICT (tenant_id, provider, metric) DO UPDATE
       SET last_status = EXCLUDED.last_status,
           alerted_at  = CASE
                             WHEN v_should THEN NOW()
                             ELSE public.provider_health_alert_dedup.alerted_at
                         END,
           updated_at  = NOW();

    RETURN v_should;
END;
$$;

COMMENT ON FUNCTION public.fn_claim_health_alert IS
    'F7 — claim atómico de alerta de salud. TRUE si el worker debe alertar '
    '(transición good→bad no notificada). Persiste el último status observado '
    'para no re-spamear tras restart. SECURITY DEFINER, solo service_role.';

GRANT EXECUTE ON FUNCTION public.fn_claim_health_alert TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_claim_health_alert FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_claim_health_alert FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_claim_health_alert FROM anon;

NOTIFY pgrst, 'reload schema';
