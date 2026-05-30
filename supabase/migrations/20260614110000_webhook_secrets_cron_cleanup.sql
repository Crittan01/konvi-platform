-- =============================================================================
-- Rev. 109 (Sem 2 cierre F.10) — fn_cleanup_webhook_secrets(): RPC para
-- limpieza periódica del grace period en tenant_webhook_secrets.
--
-- Contexto: la migración 20260514110000 creó la tabla con `previous_secret_hash`
-- + `grace_period_until` (7d default tras rotación). El verify_inbound_secret()
-- en Python acepta el secret anterior mientras grace_period_until > NOW().
--
-- Gap detectado por audit Plan K (2026-05-29): NO había cleanup automático.
-- Las filas con grace expirado quedaban con `previous_secret_hash` colgando
-- en DB — no afecta semántica (porque verify_inbound_secret() chequea
-- grace_period_until < NOW), PERO:
--   - Acumula data sensible (hashes legacy) que ya no debería existir.
--   - Dificulta auditoría: ¿está el grace activo o expirado? hay que
--     consultar la columna.
--   - Riesgo si futuro código olvida el check temporal: aceptaría secret
--     legacy indefinidamente. Defense-in-depth: NULL out post-grace.
--
-- Implementación: función SQL idempotente invocada hourly desde
-- services/ai-orchestrator/worker.py (patrón canónico, igual a
-- cleanup_expired_meli_webhook_dedup y cleanup_expired_idempotency_keys).
--
-- NO usa pg_cron porque Supabase free tier no lo expone consistentemente;
-- el worker funciona en cualquier tier (Free/Pro/Starter Render).
-- =============================================================================

CREATE OR REPLACE FUNCTION public.fn_cleanup_webhook_secrets()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    cleaned_count INTEGER := 0;
BEGIN
    -- NULL out previous_secret_hash + grace_period_until donde el grace
    -- ya expiró. NO borra la fila — el secret actual sigue activo.
    UPDATE public.tenant_webhook_secrets
       SET previous_secret_hash = NULL,
           grace_period_until   = NULL,
           updated_at           = NOW()
     WHERE grace_period_until IS NOT NULL
       AND grace_period_until  < NOW();

    GET DIAGNOSTICS cleaned_count = ROW_COUNT;
    RETURN cleaned_count;
END;
$$;

COMMENT ON FUNCTION public.fn_cleanup_webhook_secrets() IS
    'F.10 cierre: limpia grace period expirados en tenant_webhook_secrets. '
    'Invocada hourly desde services/ai-orchestrator/worker.py. Retorna '
    'cantidad de filas limpiadas (para métrica/log).';

-- Solo service_role debe poder invocar — los tenants nunca limpian secretos.
GRANT EXECUTE ON FUNCTION public.fn_cleanup_webhook_secrets() TO service_role;

-- Revocar EXECUTE de authenticated/anon como defensa (idempotente — Postgres
-- ignora si ya no estaba).
REVOKE EXECUTE ON FUNCTION public.fn_cleanup_webhook_secrets() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_cleanup_webhook_secrets() FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_cleanup_webhook_secrets() FROM anon;
