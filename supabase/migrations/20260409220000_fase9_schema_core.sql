-- =============================================================================
-- Fase 9 — Schema Core: Contacts, Orders, tenant_integrations, notification_settings
-- Prerequisito de Fase 10 (MeLi + Envia) y Fase 11 (métricas, auditoría)
-- =============================================================================

-- ── Contacts ────────────────────────────────────────────────────────────────
-- Base de clientes del tenant. Identificados por teléfono.
-- Inicialmente se crean manualmente; en Fase 11 se auto-poblarán desde conversations.

CREATE TABLE public.contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    phone           TEXT NOT NULL,
    name            TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, phone)
);

-- ── Orders ──────────────────────────────────────────────────────────────────
-- Pedidos del tenant. Pueden originarse en WhatsApp (via conversación)
-- o crearse manualmente desde el backoffice.
-- Estados: pending → confirmed → processing → shipped → delivered | cancelled

CREATE TABLE public.orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES public.contacts(id) ON DELETE SET NULL,
    conversation_id UUID REFERENCES public.conversations(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    total_amount    DECIMAL(10,2) NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Order Items ─────────────────────────────────────────────────────────────
-- Ítems de cada pedido. Preservan snapshot de título y precio al momento del pedido.
-- product_id / variation_id son nullable para mantener histórico si el producto se borra.

CREATE TABLE public.order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    product_id      UUID REFERENCES public.products(id) ON DELETE SET NULL,
    variation_id    UUID REFERENCES public.product_variations(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,         -- snapshot del título al crear el pedido
    unit_price      DECIMAL(10,2) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Tenant Integrations ─────────────────────────────────────────────────────
-- Prerequisito crítico de Fase 10 (MeLi + Envia).
-- credentials es JSONB — cifrar tokens en Fase 10 antes de guardar credenciales reales.

CREATE TABLE public.tenant_integrations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,             -- 'mercadolibre', 'envia'
    status      TEXT NOT NULL DEFAULT 'disconnected', -- connected, disconnected, error
    credentials JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- user_id MeLi, shop_id, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, provider)
);

-- ── Notification Settings ───────────────────────────────────────────────────
-- Configuración de alertas por canal por tenant.
-- R-08: canal Telegram pendiente de implementar.

CREATE TABLE public.notification_settings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,   -- 'telegram', 'email'
    enabled     BOOLEAN NOT NULL DEFAULT false,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- bot_token, chat_id, email, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, channel)
);

-- ── RLS ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.contacts             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orders               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.order_items          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_integrations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation" ON public.contacts
    FOR ALL USING (tenant_id = app_current_tenant());

CREATE POLICY "Tenant Isolation" ON public.orders
    FOR ALL USING (tenant_id = app_current_tenant());

CREATE POLICY "Tenant Isolation" ON public.order_items
    FOR ALL USING (tenant_id = app_current_tenant());

CREATE POLICY "Tenant Isolation" ON public.tenant_integrations
    FOR ALL USING (tenant_id = app_current_tenant());

CREATE POLICY "Tenant Isolation" ON public.notification_settings
    FOR ALL USING (tenant_id = app_current_tenant());

-- ── Helper: Get tenant team with emails ─────────────────────────────────────
-- Función SECURITY DEFINER para que el frontend pueda listar miembros del equipo
-- con su email sin exponer la tabla auth.users directamente.

CREATE OR REPLACE FUNCTION get_tenant_team()
RETURNS TABLE (user_id UUID, email TEXT, role TEXT, joined_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        tu.user_id,
        au.email,
        tu.role,
        tu.created_at AS joined_at
    FROM public.tenant_users tu
    JOIN auth.users au ON au.id = tu.user_id
    WHERE tu.tenant_id = app_current_tenant()
    ORDER BY tu.created_at ASC;
END;
$$;

-- ── Índices ─────────────────────────────────────────────────────────────────

CREATE INDEX idx_contacts_tenant ON public.contacts(tenant_id);
CREATE INDEX idx_contacts_phone ON public.contacts(tenant_id, phone);
CREATE INDEX idx_orders_tenant ON public.orders(tenant_id);
CREATE INDEX idx_orders_status ON public.orders(tenant_id, status);
CREATE INDEX idx_orders_contact ON public.orders(contact_id);
CREATE INDEX idx_order_items_order ON public.order_items(order_id);
CREATE INDEX idx_tenant_integrations_tenant ON public.tenant_integrations(tenant_id);
