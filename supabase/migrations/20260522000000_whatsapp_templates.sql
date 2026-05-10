-- =============================================================================
-- whatsapp_templates — HSM templates registry per-tenant (Sem 7 F2 / 2026-05-09).
--
-- Fuente única de verdad para los Highly Structured Messages (HSM) de Meta
-- WhatsApp Cloud API. Cada tenant define sus propios templates dentro de SU
-- WABA. La plataforma:
--   1. Persiste el template aquí en estado LOCAL_DRAFT.
--   2. Submitea a Meta vía POST /{WABA_ID}/message_templates → estado PENDING.
--   3. Sincroniza status via webhook `message_template_status_update`.
--   4. Solo templates en estado APPROVED se pueden usar para outbound proactivo
--      (recordatorios pago, abandoned cart, order_shipped, etc.) fuera CSW 24h.
--
-- Refs documentación oficial:
--   docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5 (Template lifecycle)
--   https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates/
--
-- Estados (CHECK):
--   LOCAL_DRAFT      — creado en Konvi, aún no enviado a Meta.
--   PENDING          — submitted a Meta, esperando review (~15min-48h).
--   APPROVED         — Meta aprobó. Único estado válido para SEND.
--   REJECTED         — Meta rechazó. Razón en status_reason.
--   PAUSED           — Meta pausó por quality drop. Re-aprueba si mejora.
--   DISABLED         — Meta deshabilitó (policy violation grave).
--   FLAGGED          — Meta marcó pero permite envío con warning quality.
--   LIMIT_EXCEEDED   — Tier exceeded; templates marketing pausados.
--
-- Categories (CHECK):
--   MARKETING        — siempre paid; promos, abandoned cart.
--   UTILITY          — gratis dentro CSW 24h; transaccional (order_confirmation,
--                      payment_reminder, order_shipped, delivery_notification).
--   AUTHENTICATION   — paid; OTP, verification codes.
--
-- RLS: FOR ALL con `app_current_tenant()` (consistente con tenant_carriers,
-- tenant_provider_capabilities y demás tablas accedidas desde JWT user).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.whatsapp_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,

    -- Identidad Meta
    meta_template_id TEXT,
    waba_id TEXT NOT NULL,

    -- Definición del template (lo que se envía a Meta en POST /message_templates)
    name TEXT NOT NULL,
    language TEXT NOT NULL,
    category TEXT NOT NULL,
    components JSONB NOT NULL,
    parameter_format TEXT NOT NULL DEFAULT 'POSITIONAL',

    -- Estado lifecycle (sync via webhook message_template_status_update)
    status TEXT NOT NULL DEFAULT 'LOCAL_DRAFT',
    status_reason TEXT,
    quality_rating TEXT NOT NULL DEFAULT 'UNKNOWN',

    -- Audit
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,

    -- CHECK constraints
    CONSTRAINT chk_whatsapp_templates_category
        CHECK (category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')),
    CONSTRAINT chk_whatsapp_templates_status
        CHECK (status IN ('LOCAL_DRAFT', 'PENDING', 'APPROVED', 'REJECTED',
                          'PAUSED', 'DISABLED', 'FLAGGED', 'LIMIT_EXCEEDED')),
    CONSTRAINT chk_whatsapp_templates_parameter_format
        CHECK (parameter_format IN ('POSITIONAL', 'NAMED')),
    CONSTRAINT chk_whatsapp_templates_quality_rating
        CHECK (quality_rating IN ('GREEN', 'YELLOW', 'RED', 'UNKNOWN')),
    CONSTRAINT chk_whatsapp_templates_name_format
        CHECK (name ~ '^[a-z][a-z0-9_]{2,49}$'),
    CONSTRAINT chk_whatsapp_templates_language_format
        CHECK (language ~ '^[a-z]{2}(_[A-Z]{2})?$'),

    -- UNIQUE constraints
    -- Mismo nombre+lang único per tenant (un tenant no puede tener 2 versiones
    -- del mismo nombre y lenguaje — debe versionar como name_v1, name_v2).
    CONSTRAINT uq_whatsapp_templates_tenant_name_lang
        UNIQUE (tenant_id, name, language)
);

-- Indexes para queries frecuentes
CREATE INDEX idx_whatsapp_templates_tenant
    ON public.whatsapp_templates(tenant_id);
CREATE INDEX idx_whatsapp_templates_status
    ON public.whatsapp_templates(tenant_id, status);
CREATE INDEX idx_whatsapp_templates_meta_id
    ON public.whatsapp_templates(meta_template_id)
    WHERE meta_template_id IS NOT NULL;
CREATE INDEX idx_whatsapp_templates_waba
    ON public.whatsapp_templates(waba_id);

-- Trigger updated_at automático (patrón consistente con resto del schema)
CREATE OR REPLACE FUNCTION public.tg_whatsapp_templates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_whatsapp_templates_updated_at
    ON public.whatsapp_templates;
CREATE TRIGGER trg_whatsapp_templates_updated_at
    BEFORE UPDATE ON public.whatsapp_templates
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_whatsapp_templates_updated_at();

-- RLS habilitado
ALTER TABLE public.whatsapp_templates ENABLE ROW LEVEL SECURITY;

-- Policy FOR ALL con tenant scope. Usa public.app_current_tenant()
-- (consistente con tenant_carriers, tenant_provider_capabilities, coupons).
DROP POLICY IF EXISTS whatsapp_templates_tenant_iud
    ON public.whatsapp_templates;
CREATE POLICY whatsapp_templates_tenant_iud
    ON public.whatsapp_templates
    FOR ALL
    USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

COMMENT ON TABLE public.whatsapp_templates IS
    'HSM templates per-tenant para Meta WhatsApp Cloud API. Cada template '
    'pasa por lifecycle LOCAL_DRAFT → PENDING (submit) → APPROVED/REJECTED. '
    'Solo APPROVED se puede usar para outbound proactivo fuera CSW 24h. '
    'Sync de status via webhook message_template_status_update.';

COMMENT ON COLUMN public.whatsapp_templates.meta_template_id IS
    'ID retornado por Meta tras POST /{WABA_ID}/message_templates. NULL '
    'mientras el template esté en LOCAL_DRAFT (no submitted aún).';

COMMENT ON COLUMN public.whatsapp_templates.components IS
    'Array JSONB con estructura Meta: HEADER (text/image/video/doc), BODY '
    '(texto con placeholders {{1}} o {{name}}), FOOTER (texto opcional), '
    'BUTTONS (QUICK_REPLY/URL/PHONE_NUMBER/COPY_CODE/OTP). Ver dossier '
    'docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5.';

COMMENT ON COLUMN public.whatsapp_templates.parameter_format IS
    'POSITIONAL = placeholders {{1}}, {{2}} (default histórico). '
    'NAMED = placeholders {{customer_name}}, {{order_id}} (Meta v22+). '
    'Mutuamente excluyentes en mismo template.';

COMMENT ON CONSTRAINT chk_whatsapp_templates_name_format
    ON public.whatsapp_templates IS
    'Meta exige: lowercase + dígitos + underscores, 3-50 chars, debe '
    'empezar con letra. Ejemplos: payment_reminder_v1, order_shipped, '
    'cart_abandoned_24h.';
