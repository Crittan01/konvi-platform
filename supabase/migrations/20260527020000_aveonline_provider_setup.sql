-- Rev. 107 O.1 — Setup schema para provider Aveonline.
--
-- Objetivos (alineado con ADR-0019 + dossier §22):
--   1. Tabla `tenant_shipping_provider_config` con `active_provider` ENUM:
--      cada tenant tiene UN provider activo (Envia O Aveonline).
--      NO hay fallback automático (decisión arquitectónica 2026-05-22).
--   2. RPC helper `get_aveonline_credentials(tenant_id)` que resuelve
--      credenciales sensibles desde Vault (espejo del patrón Envia/Wompi).
--   3. NO se modifica `tenant_integrations.provider` constraint porque
--      hoy NO existe constraint estricto — solo TEXT con comentario.
--   4. Seed: tenants existentes arrancan con `active_provider='envia'`
--      preservando comportamiento actual sin breaking change.
--
-- Patrón replicado del repo existente:
--   • Vault via pgsec_* RPCs (migración 20260426020000_vault_setup_*).
--   • tenant_integrations.credentials JSONB con *_secret_id apuntando a Vault.
--   • Naming: vault secret name = "<tenant_id>/<provider>/<credential>".

-- ── 1. Tabla active_provider per-tenant ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tenant_shipping_provider_config (
    tenant_id          UUID PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    active_provider    TEXT NOT NULL DEFAULT 'envia'
        CHECK (active_provider IN ('envia', 'aveonline')),
    enabled_carriers   TEXT[] NOT NULL DEFAULT '{}',
    cod_enabled        BOOLEAN NOT NULL DEFAULT false,
    insurance_strategy TEXT NOT NULL DEFAULT 'on_demand'
        CHECK (insurance_strategy IN ('always', 'on_demand', 'never')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.tenant_shipping_provider_config IS
    'Provider de despachos activo per-tenant. Single provider (sin fallback '
    'automático). Switcher en UI Tenant Console → Settings → Despachos. '
    'Decisión: ADR-0019 rev. 107.';

COMMENT ON COLUMN public.tenant_shipping_provider_config.active_provider IS
    'Provider HOY usado para cotizar y generar guías nuevas. Cambiar al '
    'otro provider NO migra guías legacy — éstas siguen rastreándose en '
    'el provider original (read-only).';

-- Índice para queries de operación (admin: "¿qué tenants usan Aveonline?")
CREATE INDEX IF NOT EXISTS tenant_shipping_provider_config_active_idx
    ON public.tenant_shipping_provider_config (active_provider);

-- RLS: cada tenant solo ve su propia config.
ALTER TABLE public.tenant_shipping_provider_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY tspc_select_own_tenant
    ON public.tenant_shipping_provider_config
    FOR SELECT
    USING (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
        )
    );

CREATE POLICY tspc_modify_own_tenant
    ON public.tenant_shipping_provider_config
    FOR ALL
    USING (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
              AND tu.role IN ('owner', 'manager')
        )
    );

-- Trigger updated_at automático.
CREATE OR REPLACE FUNCTION public.tenant_shipping_provider_config_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tspc_set_updated_at
    BEFORE UPDATE ON public.tenant_shipping_provider_config
    FOR EACH ROW
    EXECUTE FUNCTION public.tenant_shipping_provider_config_set_updated_at();

-- Seed: tenants existentes arrancan con 'envia' (preserva comportamiento).
INSERT INTO public.tenant_shipping_provider_config (tenant_id, active_provider)
SELECT id, 'envia' FROM public.tenants
ON CONFLICT (tenant_id) DO NOTHING;


-- ── 2. RPC helper para resolver credenciales Aveonline ───────────────────────
--
-- Retorna un dict con campos sensibles (password resuelto via Vault).
-- Llamable desde Python: supabase.rpc("get_aveonline_credentials",
-- {"p_tenant_id": <uuid>}).
--
-- Diseño defensivo:
--   • Retorna NULL si no hay row en tenant_integrations para Aveonline.
--   • Retorna NULL si row existe pero password_secret_id no.
--   • SECURITY DEFINER para que el RPC pueda leer vault.decrypted_secrets
--     sin requerir grant directo a authenticated.

CREATE OR REPLACE FUNCTION public.get_aveonline_credentials(p_tenant_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, vault, pg_catalog
AS $$
DECLARE
    v_creds   JSONB;
    v_secret  TEXT;
    v_pass_id UUID;
BEGIN
    -- Verificación tenant_users (defensa: solo authenticated del tenant
    -- pueden ejecutar esto via API). El service_role bypasa porque
    -- maneja todos los tenants.
    IF auth.uid() IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = p_tenant_id AND user_id = auth.uid()
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT credentials INTO v_creds
    FROM public.tenant_integrations
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline'
      AND status = 'connected'
    LIMIT 1;

    IF v_creds IS NULL THEN
        RETURN NULL;
    END IF;

    -- Resolver password desde Vault (si está almacenado).
    v_pass_id := NULLIF(v_creds->>'password_secret_id', '')::uuid;
    IF v_pass_id IS NOT NULL THEN
        SELECT decrypted_secret INTO v_secret
        FROM vault.decrypted_secrets
        WHERE id = v_pass_id;
        v_creds := v_creds || jsonb_build_object('password', v_secret);
    END IF;

    -- Retornar credentials con password resuelto.
    -- Campos esperados: usuario, password (resuelto), empresa_id,
    -- asesorlogistico, nombreasesor, jwt_token, jwt_expires_at,
    -- tiempoToken, auth_version.
    RETURN v_creds;
END;
$$;

COMMENT ON FUNCTION public.get_aveonline_credentials IS
    'Retorna credenciales Aveonline del tenant con password resuelto desde '
    'Vault. NULL si no hay integración connected. Usado por AveonlineClient '
    'al refresh JWT en runtime.';

GRANT EXECUTE ON FUNCTION public.get_aveonline_credentials TO authenticated, service_role;


-- ── 3. RPC helper para actualizar credenciales (rotar password / JWT) ─────

CREATE OR REPLACE FUNCTION public.upsert_aveonline_jwt(
    p_tenant_id     UUID,
    p_jwt_token     TEXT,
    p_jwt_expires_at TIMESTAMPTZ
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
BEGIN
    UPDATE public.tenant_integrations
    SET credentials = credentials
        || jsonb_build_object(
            'jwt_token', p_jwt_token,
            'jwt_expires_at', p_jwt_expires_at
        )
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline';
END;
$$;

COMMENT ON FUNCTION public.upsert_aveonline_jwt IS
    'Actualiza JWT cacheado del tenant tras refresh exitoso del client. '
    'Idempotente — solo escribe los 2 campos JWT, preserva resto de '
    'credentials (usuario, password_secret_id, empresa_id, etc.).';

GRANT EXECUTE ON FUNCTION public.upsert_aveonline_jwt TO authenticated, service_role;
