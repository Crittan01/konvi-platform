-- =============================================================================
-- Conformidad Aveonline 2026-08-22 — RPC `upsert_aveonline_idagente`
--
-- Contexto: el `idagente` (dirección de despacho Aveonline) es REQUERIDO por
-- la doc oficial de cotización; sin él Aveonline auto-calcula pero con MENOS
-- carriers (verificado live 2026-08-22 con la cuenta demo: sin idagente la
-- cotización Bogotá→Bogotá pierde INTERRAPIDISIMO).
--
-- El cliente (`AveonlineClient._resolve_idagente`) lo auto-resuelve vía
-- `listarAgentesPorEmpresaAuth` (agente con principal=SI) cuando el tenant
-- no lo eligió manualmente en la UI, y lo persiste aquí para que TODOS los
-- procesos (api / orchestrator / worker) reusan el mismo valor (SoT en
-- `tenant_integrations.credentials.idagente`).
--
-- Mismo patrón que `upsert_aveonline_jwt` (20260527020000): merge jsonb
-- atómico — no pisa jwt_token ni otros campos de credentials.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.upsert_aveonline_idagente(
    p_tenant_id  UUID,
    p_idagente   TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
BEGIN
    UPDATE public.tenant_integrations
    SET credentials = credentials
        || jsonb_build_object('idagente', p_idagente)
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline';
END;
$$;

COMMENT ON FUNCTION public.upsert_aveonline_idagente IS
    'Persiste el idagente Aveonline auto-resuelto (listarAgentes → principal) '
    'en tenant_integrations.credentials.idagente. Merge jsonb atómico — '
    'preserva jwt_token y demás campos. Best-effort desde AveonlineClient.';

GRANT EXECUTE ON FUNCTION public.upsert_aveonline_idagente TO authenticated, service_role;
