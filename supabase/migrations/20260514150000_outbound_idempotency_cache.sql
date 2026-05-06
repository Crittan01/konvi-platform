-- =============================================================================
-- Rev. 105 (Sem 2, F.2 / MA-1) — outbound_idempotency_cache: cache de
-- responses para llamadas POST a APIs externas, evita doble efecto en retries.
--
-- Disparador: meta-análisis cross-dossier 2026-05-05 — 6 de 9 providers NO
-- tienen Idempotency-Key server-side. Sin cache local, un retry tras
-- timeout puede crear 2 labels Envia, 2 transacciones Wompi, etc.
--
-- Patrón:
--   1. Cliente computa request_hash = SHA256(method + url + sorted_body)
--   2. Antes del POST, lookup tabla por (provider, tenant_id, request_hash)
--   3. Hit → return response cached (no hit a provider)
--   4. Miss → POST + cache response con TTL configurable per provider
--   5. Cleanup vía cron diario para purgar expirados
--
-- Riesgo manejado: cliente HTTP timeout pero provider sí completó. El retry
-- vuelve a hashear el mismo body y devuelve el response cached, evitando
-- duplicar el efecto.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.outbound_idempotency_cache (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,
        -- 'envia' | 'wompi' | 'meli' | 'meta' | 'telegram' | 'resend'
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    request_hash    TEXT NOT NULL,
        -- SHA256 hex (64 chars) de method + url + sorted_body normalizado.
    response_status INTEGER NOT NULL,
        -- HTTP status del response cacheado (e.g. 201, 200, 4xx).
    response_body   JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Body completo del response del provider para retornar al retry.
    response_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Headers relevantes del response (idempotency-key, request-id, etc.).
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
        -- TTL: típicamente 24h para POSTs, configurable per provider.

    CONSTRAINT outbound_idempotency_cache_uniq
        UNIQUE (provider, tenant_id, request_hash)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Lookup principal antes de POST.
CREATE INDEX IF NOT EXISTS outbound_idempotency_cache_lookup_idx
    ON public.outbound_idempotency_cache (provider, tenant_id, request_hash);

-- Cleanup TTL — eventos expirados purgables.
CREATE INDEX IF NOT EXISTS outbound_idempotency_cache_expires_idx
    ON public.outbound_idempotency_cache (expires_at);

-- ─── RPC atómica check_or_register ──────────────────────────────────────────
-- Patrón: SELECT-existing-OR-NULL atómico. Si existe → retorna response;
-- caller decide retry safely. Si NULL → caller hace POST y luego inserta.

CREATE OR REPLACE FUNCTION public.outbound_idempotency_lookup(
    p_provider     TEXT,
    p_tenant_id    UUID,
    p_request_hash TEXT
)
RETURNS TABLE (
    response_status INTEGER,
    response_body   JSONB,
    response_headers JSONB,
    created_at      TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT c.response_status, c.response_body, c.response_headers, c.created_at
    FROM public.outbound_idempotency_cache c
    WHERE c.provider = p_provider
      AND c.tenant_id = p_tenant_id
      AND c.request_hash = p_request_hash
      AND c.expires_at > NOW()
    LIMIT 1;
END;
$$;

-- Insert atómico tras POST exitoso. ON CONFLICT DO NOTHING evita race
-- conditions cuando 2 requests concurrentes con mismo hash llegan.
CREATE OR REPLACE FUNCTION public.outbound_idempotency_register(
    p_provider     TEXT,
    p_tenant_id    UUID,
    p_request_hash TEXT,
    p_status       INTEGER,
    p_body         JSONB,
    p_headers      JSONB,
    p_ttl_seconds  INTEGER DEFAULT 86400
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    INSERT INTO public.outbound_idempotency_cache (
        provider, tenant_id, request_hash, response_status,
        response_body, response_headers, expires_at
    ) VALUES (
        p_provider, p_tenant_id, p_request_hash, p_status,
        p_body, p_headers, NOW() + (p_ttl_seconds || ' seconds')::INTERVAL
    )
    ON CONFLICT (provider, tenant_id, request_hash) DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN (v_inserted > 0);
END;
$$;

-- Cleanup cron — borra expirados. Llamar daily desde pg_cron o worker.
CREATE OR REPLACE FUNCTION public.outbound_idempotency_cleanup()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM public.outbound_idempotency_cache
    WHERE expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.outbound_idempotency_cache ENABLE ROW LEVEL SECURITY;

-- SELECT: tenant ve sus propios entries (UI Settings → "Cache outbound").
DROP POLICY IF EXISTS outbound_idempotency_cache_tenant_select
    ON public.outbound_idempotency_cache;
CREATE POLICY outbound_idempotency_cache_tenant_select
    ON public.outbound_idempotency_cache
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT/UPDATE/DELETE: solo via RPC SECURITY DEFINER (service_role).

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.outbound_idempotency_cache IS
    'Cache de responses outbound POST per (provider, tenant, request_hash). '
    'Rev. 105 Sem 2 F.2 (MA-1). Evita doble efecto en retries cuando provider '
    'completó pero cliente HTTP timeout. TTL típico 24h; cleanup pg_cron diario.';

COMMENT ON FUNCTION public.outbound_idempotency_lookup IS
    'Pre-POST lookup. Retorna fila si hash ya cacheado y vigente; vacío si miss.';

COMMENT ON FUNCTION public.outbound_idempotency_register IS
    'Post-POST insert. ON CONFLICT DO NOTHING evita race conditions. '
    'Retorna TRUE si insertado, FALSE si ya existía (concurrencia).';

COMMENT ON FUNCTION public.outbound_idempotency_cleanup IS
    'Cron daily. Borra entries con expires_at < NOW(). Retorna count borrado.';
