-- =============================================================================
-- Rev. 103 — Fix tipo retorno RPC public.rate_limit_hit.
--
-- Bug runtime detectado en api.log:
--   "structure of query does not match function result type
--    Returned type bigint does not match expected type integer in column 3"
--
-- Causa: en la migración original `20260425000000_distributed_rate_limiter.sql`
-- el RPC declara `RETURNS TABLE (allowed BOOLEAN, remaining INTEGER, reset_in INTEGER)`
-- pero la columna `reset_in` se calcula como:
--   GREATEST(0, v_window_start + p_window_seconds - ::INTEGER)
-- donde `v_window_start` es BIGINT → la operación BIGINT + INT = BIGINT,
-- que no encaja con `reset_in INTEGER`. PostgreSQL rechaza el RETURN QUERY.
--
-- Resultado: el rate limiter caía siempre al fallback in-memory (warning
-- "[RL] RPC rate_limit_hit falló — usando in-memory como fallback") y
-- quedaba sin protección distribuida cross-réplica.
--
-- Fix: cast explícito a INTEGER en `reset_in` antes del RETURN.
-- =============================================================================

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
    v_window_start := (FLOOR(EXTRACT(EPOCH FROM NOW()) / p_window_seconds)::BIGINT) * p_window_seconds;
    v_window_key   := p_key || ':' || v_window_start::TEXT;
    v_expires_at   := TO_TIMESTAMP(v_window_start + p_window_seconds);

    INSERT INTO public.rate_limit_windows (window_key, count, expires_at)
    VALUES (v_window_key, 1, v_expires_at)
    ON CONFLICT (window_key)
    DO UPDATE SET count = rate_limit_windows.count + 1
    RETURNING rate_limit_windows.count INTO v_count;

    RETURN QUERY SELECT
        (v_count <= p_limit)                                            AS allowed,
        GREATEST(0, p_limit - v_count)                                  AS remaining,
        -- Rev. 103 — cast explícito a INTEGER. La aritmética BIGINT+INT
        -- producía BIGINT y el RETURN QUERY rechazaba por mismatch.
        GREATEST(
            0,
            (v_window_start + p_window_seconds - EXTRACT(EPOCH FROM NOW())::BIGINT)::INTEGER
        )                                                               AS reset_in;
END;
$$;
