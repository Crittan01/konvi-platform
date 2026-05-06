-- =============================================================================
-- Rev. 105 (Sem 2, F.3) — tenant_provider_capabilities: matrix runtime de
-- features habilitadas per-tenant per-provider per-capability.
--
-- Disparador: Plan A.7 + meta-análisis cross-dossier 2026-05-05 — cada provider
-- tiene capabilities heterogéneas (Envia: COD, insurance, label generation,
-- pickup, cancel; Wompi: payment methods PSE/Nequi/Bancolombia/tarjeta;
-- WhatsApp: HSM templates tier, location/document/interactive types; MeLi:
-- Q&A reply, messages post-venta, order ack; Telegram: multi-bot commands).
--
-- Sin esta tabla, capabilities están hardcoded en `tenant_integrations.meta`
-- como JSONB libre (sin estructura, sin índices, sin RLS por capability).
-- Esta tabla los formaliza con (capability, enabled, config) tipado.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_provider_capabilities (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
        -- 'envia' | 'wompi' | 'meta' | 'meli' | 'telegram' | 'resend'
    capability      TEXT NOT NULL,
        -- snake_case namespace per-provider:
        --   envia:     'cod' | 'insurance' | 'label_generation' | 'pickup' |
        --              'cancel' | 'tracking_polling'
        --   wompi:     'payment_method_card' | 'payment_method_pse' |
        --              'payment_method_nequi' | 'payment_method_bancolombia' |
        --              'payment_method_daviplata' | 'tokenized_cards'
        --   meta:      'hsm_templates' | 'tier_unlimited' | 'interactive_messages' |
        --              'document_outbound' | 'location_outbound' | 'commerce_catalog'
        --   meli:      'qna_reply' | 'messages_postsale' | 'order_ack' | 'cbt_compliant'
        --   telegram:  'multi_bot_per_tenant' | 'inline_keyboards' | 'callback_query'
        --   resend:    'custom_domain' | 'webhooks_delivery'
    enabled         BOOLEAN NOT NULL DEFAULT false,
        -- Toggle on/off per (tenant, provider, capability).
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Configuración específica per capability:
        --   envia.cod: {"carriers": ["servientrega", "coordinadora"], "fee_pct": 2.5}
        --   wompi.payment_method_card: {"min_amount_cents": 1000}
        --   meta.hsm_templates: {"approved": ["welcome_v1", "shipping_v2"], "tier": "10K"}
    notes           TEXT,
        -- Anotaciones humanas: razón de deshabilitar, link a contrato, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tenant_provider_capabilities_uniq
        UNIQUE (tenant_id, provider, capability)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Lookup principal (cliente HTTP / orchestrator antes de invocar feature).
CREATE INDEX IF NOT EXISTS tenant_provider_capabilities_lookup_idx
    ON public.tenant_provider_capabilities (tenant_id, provider, enabled);

-- Batch ops por capability (ej. "todos los tenants con HSM enabled").
CREATE INDEX IF NOT EXISTS tenant_provider_capabilities_capability_idx
    ON public.tenant_provider_capabilities (provider, capability, enabled);

-- ─── Trigger updated_at ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tenant_provider_capabilities_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenant_provider_capabilities_updated_at_trg
    ON public.tenant_provider_capabilities;
CREATE TRIGGER tenant_provider_capabilities_updated_at_trg
    BEFORE UPDATE ON public.tenant_provider_capabilities
    FOR EACH ROW
    EXECUTE FUNCTION public.tenant_provider_capabilities_set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.tenant_provider_capabilities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_provider_capabilities_tenant_select
    ON public.tenant_provider_capabilities;
CREATE POLICY tenant_provider_capabilities_tenant_select
    ON public.tenant_provider_capabilities
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT/UPDATE solo via service_role (admin endpoints validan permisos
-- en application layer).

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.tenant_provider_capabilities IS
    'Matrix runtime per-tenant per-provider per-capability. Rev. 105 Sem 2 F.3. '
    'Reemplaza gradualmente capabilities hardcoded en tenant_integrations.meta. '
    'Permite enable/disable feature per-tenant sin código (UI Settings → '
    'Integraciones → Capabilities).';

COMMENT ON COLUMN public.tenant_provider_capabilities.capability IS
    'snake_case namespace por provider. Ver lista canónica en lib '
    'services/api/lib/capabilities_matrix.py:CAPABILITIES_BY_PROVIDER.';

COMMENT ON COLUMN public.tenant_provider_capabilities.config IS
    'Configuración específica per capability (carriers, fees, templates, '
    'tiers, etc.). Schema validado en application layer per capability.';
