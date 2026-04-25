-- ============================================================
-- Rate limiter distribuido para API Gateway multi-réplica
-- Reemplaza el contador in-memory (single-process) por una
-- ventana deslizante en PostgreSQL atómica y sin Redis.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.rate_limit_windows (
    window_key  TEXT        NOT NULL,   -- "{tenant_id}:{bucket}:{window_epoch}"
    count       INTEGER     NOT NULL DEFAULT 1,
    expires_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (window_key)
);

-- Índice para limpieza periódica de ventanas expiradas
CREATE INDEX IF NOT EXISTS rate_limit_windows_expires_idx
    ON public.rate_limit_windows (expires_at);

-- RLS: solo service_role accede; la API usa service_role
ALTER TABLE public.rate_limit_windows ENABLE ROW LEVEL SECURITY;

-- ── RPC principal: hit atómico con UPSERT ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.rate_limit_hit(
    p_key            TEXT,
    p_limit          INTEGER,
    p_window_seconds INTEGER
)
RETURNS TABLE (allowed BOOLEAN, remaining INTEGER, reset_in INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_window_start  BIGINT;
    v_window_key    TEXT;
    v_expires_at    TIMESTAMPTZ;
    v_count         INTEGER;
BEGIN
    -- Calcular ventana actual (floor al múltiplo de window_seconds)
    v_window_start := (FLOOR(EXTRACT(EPOCH FROM NOW()) / p_window_seconds)::BIGINT) * p_window_seconds;
    v_window_key   := p_key || ':' || v_window_start::TEXT;
    v_expires_at   := TO_TIMESTAMP(v_window_start + p_window_seconds);

    -- Incremento atómico: INSERT si no existe, UPDATE si existe
    INSERT INTO public.rate_limit_windows (window_key, count, expires_at)
    VALUES (v_window_key, 1, v_expires_at)
    ON CONFLICT (window_key)
    DO UPDATE SET count = rate_limit_windows.count + 1
    RETURNING rate_limit_windows.count INTO v_count;

    RETURN QUERY SELECT
        (v_count <= p_limit)                                    AS allowed,
        GREATEST(0, p_limit - v_count)                         AS remaining,
        GREATEST(0, (v_window_start + p_window_seconds - EXTRACT(EPOCH FROM NOW())::INTEGER)) AS reset_in;
END;
$$;

-- ── RPC de limpieza de ventanas expiradas ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.cleanup_expired_rate_limit_windows(p_limit INTEGER DEFAULT 5000)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    WITH deleted AS (
        DELETE FROM public.rate_limit_windows
        WHERE expires_at < NOW()
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_deleted FROM deleted;
    RETURN v_deleted;
END;
$$;

COMMENT ON TABLE public.rate_limit_windows IS
    'Ventanas de rate limiting distribuido. Reemplaza el contador in-memory del API Gateway.';
