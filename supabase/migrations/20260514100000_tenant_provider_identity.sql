-- =============================================================================
-- Rev. 105 (Sem 2, F.12 / MA-10) — tenant_provider_identity: cross-mapping
-- registry universal entre tenants y proveedores externos.
--
-- Disparador: meta-análisis cross-dossier 2026-05-05 identificó que el
-- bug Telegram (`_send_telegram_reply` toma "primer tenant activo") es un
-- patrón GENERAL cross-provider, no específico de Telegram. Toda integración
-- multi-tenant sin identity registry tiene riesgo de cross-talk silencioso
-- (mensaje del tenant A llega al cliente del tenant B).
--
-- Esta tabla define el contrato canónico: para cada (provider, internal_id)
-- de proveedor externo, EXACTAMENTE UN tenant es dueño. La UNIQUE constraint
-- impide en SQL la asignación duplicada — el bug se vuelve imposible de
-- introducir incluso con código futuro.
--
-- Providers cubiertos: whatsapp, wompi, envia, meli, telegram, resend (futuro).
-- Tabla aditiva. NO toca `tenant_integrations` ni `notification_settings`
-- (esos siguen siendo fuente de credenciales). Esta tabla es un mapeo de
-- IDENTIDAD opaca para resolver "¿qué tenant maneja esta entidad externa?".
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_provider_identity (
    id                    BIGSERIAL PRIMARY KEY,
    tenant_id             UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider              TEXT NOT NULL,
        -- Canónico: 'whatsapp' | 'wompi' | 'envia' | 'meli' | 'telegram' | 'resend'.
        -- Validar en application layer (no constraint enum SQL — facilita extensibilidad).
    provider_internal_id  TEXT NOT NULL,
        -- Identidad opaca del provider: WABA ID, Wompi merchant_id, Envia account_id,
        -- MeLi user_id, Telegram chat_id (operador) o bot username, Resend domain.
    metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Metadata libre per provider: phone_number_id (WhatsApp), bot_username
        -- (Telegram), site_id (MeLi 'MCO'), etc.
    verified_at           TIMESTAMPTZ,
        -- Timestamp de la última verificación exitosa contra el provider.
        -- NULL = identidad declarada pero no verificada.
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraint clave: una identidad externa NO puede mapearse a 2 tenants.
    -- Esto cierra estructuralmente el bug "primer tenant activo" (Telegram dossier).
    CONSTRAINT tenant_provider_identity_external_uniq
        UNIQUE (provider, provider_internal_id)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Lookup inverso "todas las identidades de un tenant".
CREATE INDEX IF NOT EXISTS tenant_provider_identity_tenant_idx
    ON public.tenant_provider_identity (tenant_id, provider);

-- Lookup por provider para batch operations (ej. health checks).
CREATE INDEX IF NOT EXISTS tenant_provider_identity_provider_idx
    ON public.tenant_provider_identity (provider, verified_at);

-- ─── Trigger updated_at ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tenant_provider_identity_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenant_provider_identity_updated_at_trg
    ON public.tenant_provider_identity;
CREATE TRIGGER tenant_provider_identity_updated_at_trg
    BEFORE UPDATE ON public.tenant_provider_identity
    FOR EACH ROW
    EXECUTE FUNCTION public.tenant_provider_identity_set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.tenant_provider_identity ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_provider_identity_tenant_select
    ON public.tenant_provider_identity;
CREATE POLICY tenant_provider_identity_tenant_select
    ON public.tenant_provider_identity
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- service_role bypasea RLS automáticamente (insert/select/update/delete sin
-- restricción) — los webhooks inbound usan service_role para resolver
-- identidad antes de tener un tenant context establecido.

-- ─── Comentarios documentales ───────────────────────────────────────────────

COMMENT ON TABLE public.tenant_provider_identity IS
    'Cross-mapping registry tenant ↔ proveedores externos. Rev. 105 Sem 2 F.12 (MA-10). '
    'UNIQUE(provider, provider_internal_id) impide cross-tenant identity collision. '
    'Resuelve estructuralmente el bug Telegram "primer tenant activo" + clase general '
    'de bugs multi-tenant cross-talk en webhooks/clientes outbound.';

COMMENT ON COLUMN public.tenant_provider_identity.provider IS
    'Canónico snake_case: whatsapp | wompi | envia | meli | telegram | resend (futuros).';

COMMENT ON COLUMN public.tenant_provider_identity.provider_internal_id IS
    'Identidad opaca del provider externo. Ejemplos: '
    'whatsapp=WABA phone_number_id, wompi=merchant_id, envia=account_id, '
    'meli=user_id, telegram=chat_id (operador) o bot_username, resend=verified_domain.';

COMMENT ON COLUMN public.tenant_provider_identity.metadata IS
    'Metadata libre per provider: phone_number_id, bot_username, site_id, etc.';
