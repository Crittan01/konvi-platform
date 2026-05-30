-- =============================================================================
-- Rev. 105 (Sem 2, F.11 / MA-3) — credential_access_log: audit append-only
-- de accesos a credenciales per-tenant (Vault + plaintext legacy).
--
-- Disparador: meta-análisis cross-dossier 2026-05-05 identificó 9 esquemas
-- auth distintos en Vault (Wompi 4 keys, Envia bearer, MeLi OAuth 6h refresh,
-- WhatsApp System User Token, Telegram bot token, Resend API key, Render
-- API key, Cloudflare token, Supabase service_role). Sin facade unificado +
-- audit log, código está plagado de boilerplate "obtener key X de tenant Y"
-- y NO hay forensics de quién accedió a qué credencial cuándo.
--
-- Esta tabla es append-only — INSERT por cada acceso (cacheado o no).
-- Retention: 7 años por Habeas Data Ley 1581 (ART. 17 — auditoría).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.credential_access_log (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
        -- 'wompi' | 'envia' | 'meli' | 'whatsapp' | 'telegram' | 'resend' | otros.
    credential_name     TEXT NOT NULL,
        -- 'public_key' | 'private_key' | 'events_key' | 'integrity_key' | 'bot_token' |
        -- 'access_token' | 'refresh_token' | 'api_key' | etc.
    accessed_by_service TEXT NOT NULL,
        -- 'api' | 'orchestrator' | 'connector-whatsapp' | 'cron' — quién leyó.
    cache_hit           BOOLEAN NOT NULL DEFAULT false,
        -- true si el read salió de cache in-memory (no hit a Vault/DB).
    request_id          TEXT,
        -- correlación con trace request (futuro OpenTelemetry).
    accessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Forensics queries: "todos los accesos a Wompi.private_key del tenant X"
CREATE INDEX IF NOT EXISTS credential_access_log_tenant_provider_idx
    ON public.credential_access_log (tenant_id, provider, credential_name, accessed_at DESC);

-- "accesos en período" para auditoría regulatoria.
CREATE INDEX IF NOT EXISTS credential_access_log_accessed_at_idx
    ON public.credential_access_log (accessed_at DESC);

-- Por servicio (debug + métricas cache hit rate).
CREATE INDEX IF NOT EXISTS credential_access_log_service_idx
    ON public.credential_access_log (accessed_by_service, accessed_at DESC);

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.credential_access_log ENABLE ROW LEVEL SECURITY;

-- SELECT: tenant ve sus propios accesos (UI Settings → "Auditoría credenciales").
DROP POLICY IF EXISTS credential_access_log_tenant_select
    ON public.credential_access_log;
CREATE POLICY credential_access_log_tenant_select
    ON public.credential_access_log
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT: solo service_role (es append-only desde el facade).
-- UPDATE/DELETE: NO policy — append-only, retención 7 años Habeas Data.

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.credential_access_log IS
    'Audit append-only de accesos a credenciales per-tenant. Rev. 105 Sem 2 F.11 '
    '(MA-3). Habeas Data Ley 1581 ART. 17 — retención 7 años. NO contiene '
    'plaintext de credenciales; solo metadata de acceso.';
COMMENT ON COLUMN public.credential_access_log.cache_hit IS
    'true si el read salió de cache in-memory facade (TTL 5min). Útil para '
    'monitorear hit rate y detectar accesos anormales tras invalidación.';
