-- =============================================================================
-- Rev. 105 (Sem 2, F.10 / MA-2) — tenant_webhook_secrets: gestión de secretos
-- de webhook con rotación trimestral y grace period.
--
-- Contexto cross-dossier (meta-análisis 2026-05-05): 4 de 5 webhooks NO
-- tienen HMAC nativo robusto. El patrón "HMAC propio sobre URL secret-token
-- rotable per-tenant" emerge como estándar interno UNIVERSAL (no Envia-
-- específico).
--
-- Diseño:
--   - secret_hash: bcrypt del secret en plaintext. NUNCA almacenar plaintext.
--     El plaintext se devuelve UNA VEZ al rotar y se muestra al tenant para
--     copiar al panel del provider; después se descarta.
--   - rotated_at + expires_at: rotación trimestral (90d default) configurable.
--   - previous_secret_hash: el secret anterior queda válido durante grace
--     period 7d para permitir al tenant actualizar el panel del provider sin
--     downtime de webhook delivery.
--   - audit_log: append-only log de rotaciones (quién, cuándo, razón).
--
-- Providers cubiertos: envia, wompi, meta, meli, telegram. (Wompi y Meta
-- tienen sus propias firmas nativas — para ellos este secret es complementario,
-- defensa-en-profundidad. Para envia/telegram/meli es la primary defensa.)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_webhook_secrets (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    integration            TEXT NOT NULL,
        -- Canónico snake_case: 'envia' | 'wompi' | 'meta' | 'meli' | 'telegram'.
    secret_hash            TEXT NOT NULL,
        -- bcrypt hash del secret activo. NUNCA plaintext.
    previous_secret_hash   TEXT,
        -- Hash del secret anterior, válido durante grace_period_until.
    grace_period_until     TIMESTAMPTZ,
        -- Hasta cuándo previous_secret_hash sigue siendo válido. NULL = sin grace.
    rotated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at             TIMESTAMPTZ NOT NULL,
        -- Cuándo se debe rotar el secret (default rotated_at + 90 días).
    audit_log              JSONB NOT NULL DEFAULT '[]'::jsonb,
        -- Append-only: [{event:'created'|'rotated'|'revoked', actor_id, reason, at}].
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Un secret por (tenant, integration). Rotaciones actualizan in-place,
    -- no insertan filas nuevas (audit_log conserva el historial).
    CONSTRAINT tenant_webhook_secrets_uniq UNIQUE (tenant_id, integration)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Lookup por tenant para UI Settings → "Rotar secret".
CREATE INDEX IF NOT EXISTS tenant_webhook_secrets_tenant_idx
    ON public.tenant_webhook_secrets (tenant_id);

-- Cron job: encontrar secrets expirando en próximos 14d (alerta proactiva).
CREATE INDEX IF NOT EXISTS tenant_webhook_secrets_expires_idx
    ON public.tenant_webhook_secrets (expires_at);

-- Grace period cleanup: encontrar secretos con grace expirado.
CREATE INDEX IF NOT EXISTS tenant_webhook_secrets_grace_idx
    ON public.tenant_webhook_secrets (grace_period_until)
    WHERE grace_period_until IS NOT NULL;

-- ─── Trigger updated_at ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tenant_webhook_secrets_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenant_webhook_secrets_updated_at_trg
    ON public.tenant_webhook_secrets;
CREATE TRIGGER tenant_webhook_secrets_updated_at_trg
    BEFORE UPDATE ON public.tenant_webhook_secrets
    FOR EACH ROW
    EXECUTE FUNCTION public.tenant_webhook_secrets_set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.tenant_webhook_secrets ENABLE ROW LEVEL SECURITY;

-- SELECT: solo el propio tenant puede ver SUS hashes (no los plaintext, que
-- nunca se almacenan). Útil para UI Settings → estado del secret.
DROP POLICY IF EXISTS tenant_webhook_secrets_tenant_select
    ON public.tenant_webhook_secrets;
CREATE POLICY tenant_webhook_secrets_tenant_select
    ON public.tenant_webhook_secrets
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT/UPDATE/DELETE: solo service_role (el endpoint de rotación usa
-- service_role para validar permisos en application layer).

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.tenant_webhook_secrets IS
    'Secretos de webhook per-tenant per-integration con rotación trimestral. '
    'Rev. 105 Sem 2 F.10 (MA-2). Secret plaintext NUNCA almacenado — solo '
    'bcrypt hash. Rotación retorna plaintext una vez para copiar al panel '
    'del provider, después se descarta. Grace period 7d permite migración '
    'sin downtime cuando tenant actualiza panel.';

COMMENT ON COLUMN public.tenant_webhook_secrets.secret_hash IS
    'bcrypt(secret_plaintext). NUNCA plaintext aquí.';

COMMENT ON COLUMN public.tenant_webhook_secrets.previous_secret_hash IS
    'Hash del secret anterior. Válido durante grace_period_until para evitar '
    'downtime de webhook delivery cuando tenant actualiza panel del provider.';

COMMENT ON COLUMN public.tenant_webhook_secrets.audit_log IS
    'Append-only [{event, actor_id, reason, at}]. event ∈ created|rotated|revoked.';
