-- =============================================================================
-- Coupons engine — Sem 6 I.2 (rev. 105)
-- Fecha: 2026-05-07
-- ADR: docs/adr/0015-coupon-engine.md
--
-- Catálogo de cupones per tenant + audit append-only de redemptions +
-- columns en conversation_carts para estado materializado.
--
-- Decisiones clave (ver ADR-0015):
-- - 3 tipos: percent | fixed_amount | free_shipping (mutuamente excluyentes).
-- - NO combinables (P1) — solo 1 cupón por cart.
-- - redemptions_count se incrementa SOLO en orden APPROVED (D5).
-- - coupon_redemptions append-only (Habeas Data audit).
-- =============================================================================

-- ── 1. Catálogo de cupones ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.coupons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,                 -- 'PROMO10', 'BIENVENIDO'
    description     TEXT,                          -- mostrado a admin tenant en UI

    -- Tipo + valor (mutuamente excluyentes per CHECK).
    discount_type   TEXT NOT NULL
                    CHECK (discount_type IN ('percent', 'fixed_amount', 'free_shipping')),
    discount_value  INTEGER NOT NULL CHECK (discount_value >= 0),
    -- percent:        0-100 (entero porcentaje)
    -- fixed_amount:   cents (BIGINT representado en INTEGER es OK aquí: max ~21M COP)
    -- free_shipping:  ignorado (= shipping_cents al apply)

    -- Limits.
    min_subtotal_cents BIGINT NOT NULL DEFAULT 0 CHECK (min_subtotal_cents >= 0),
    max_redemptions    INTEGER CHECK (max_redemptions IS NULL OR max_redemptions > 0),
    redemptions_count  INTEGER NOT NULL DEFAULT 0 CHECK (redemptions_count >= 0),
    valid_from         TIMESTAMPTZ,
    valid_until        TIMESTAMPTZ,
    is_active          BOOLEAN NOT NULL DEFAULT true,

    -- Audit.
    created_by         UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Validations cross-column.
    CHECK (
        valid_until IS NULL
        OR valid_from IS NULL
        OR valid_until > valid_from
    ),
    CHECK (
        (discount_type = 'percent' AND discount_value <= 100)
        OR discount_type IN ('fixed_amount', 'free_shipping')
    ),
    -- redemptions_count NUNCA debe superar max_redemptions (defensa adicional).
    CHECK (
        max_redemptions IS NULL
        OR redemptions_count <= max_redemptions
    )
);

-- Code unique por tenant (case-sensitive — tenant decide casing).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_coupons_tenant_code
    ON public.coupons(tenant_id, code);

-- Lookup activos por tenant.
CREATE INDEX IF NOT EXISTS idx_coupons_tenant_active
    ON public.coupons(tenant_id, is_active);

-- RLS.
ALTER TABLE public.coupons ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation Coupons" ON public.coupons
    FOR ALL
    USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());


-- ── 2. Audit append-only de redemptions ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.coupon_redemptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    coupon_id       UUID NOT NULL REFERENCES public.coupons(id) ON DELETE CASCADE,

    -- Vinculación poly-state. Cart durante conversación; orden al confirmar.
    -- contact_id NULL si cliente sin consent (Habeas Data).
    cart_id         UUID REFERENCES public.conversation_carts(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES public.contacts(id) ON DELETE SET NULL,
    order_id        UUID REFERENCES public.orders(id) ON DELETE SET NULL,

    -- Snapshot del descuento al momento del apply. Si shipping cambia
    -- en free_shipping, el row queda con este monto histórico; el cart
    -- materializado (conversation_carts.discount_cents) tiene el actual.
    discount_applied_cents BIGINT NOT NULL CHECK (discount_applied_cents >= 0),

    -- FSM:
    --   applied  → cart vivo con cupón aplicado (no consumido aún).
    --   consumed → orden APPROVED (counted en coupons.redemptions_count).
    --   revoked  → cliente removió o cart cancelled/abandoned.
    status          TEXT NOT NULL DEFAULT 'applied'
                    CHECK (status IN ('applied', 'consumed', 'revoked')),

    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at     TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,

    -- Validations FSM.
    CHECK (
        (status = 'applied'  AND consumed_at IS NULL AND revoked_at IS NULL)
        OR (status = 'consumed' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
        OR (status = 'revoked'  AND revoked_at  IS NOT NULL AND consumed_at IS NULL)
    )
);

-- Lookup por cart (estado activo del cart).
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_cart
    ON public.coupon_redemptions(cart_id, status);

-- Lookup por coupon (count redemptions consumed, audit).
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon
    ON public.coupon_redemptions(coupon_id, status);

-- Lookup por order (consumed_at lookup tras webhook APPROVED).
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_order
    ON public.coupon_redemptions(order_id) WHERE order_id IS NOT NULL;

-- Tenant scope (RLS + queries operativas).
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant
    ON public.coupon_redemptions(tenant_id);

-- Habeas Data SAR: lookup por contact_id.
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_contact
    ON public.coupon_redemptions(contact_id) WHERE contact_id IS NOT NULL;

-- UNIQUE parcial: solo 1 redemption ACTIVO por cart (D3 NO combinables P1).
-- Cuando status='applied', cart_id debe ser único.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_coupon_redemption_cart_applied
    ON public.coupon_redemptions(cart_id)
    WHERE status = 'applied' AND cart_id IS NOT NULL;

-- RLS.
ALTER TABLE public.coupon_redemptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation Coupon Redemptions" ON public.coupon_redemptions
    FOR ALL
    USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());


-- ── 3. Columnas estado materializado en conversation_carts ──────────────────

ALTER TABLE public.conversation_carts
    ADD COLUMN IF NOT EXISTS coupon_id UUID REFERENCES public.coupons(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS coupon_code TEXT,
    ADD COLUMN IF NOT EXISTS discount_cents BIGINT NOT NULL DEFAULT 0
        CHECK (discount_cents >= 0);

-- Para fast-lookup carts con cupón activo (analytics + admin).
CREATE INDEX IF NOT EXISTS idx_conversation_carts_coupon
    ON public.conversation_carts(coupon_id) WHERE coupon_id IS NOT NULL;


-- ── 4. Trigger updated_at automatic ─────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tg_coupons_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coupons_updated_at ON public.coupons;
CREATE TRIGGER coupons_updated_at
    BEFORE UPDATE ON public.coupons
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_coupons_set_updated_at();


-- ── 5. Comments documentacion ────────────────────────────────────────────────

COMMENT ON TABLE public.coupons IS
'Catálogo de cupones per tenant. ADR-0015. discount_type=(percent|fixed_amount|free_shipping). redemptions_count se incrementa SOLO en orden APPROVED (D5).';

COMMENT ON TABLE public.coupon_redemptions IS
'Audit append-only de aplicaciones/consumos/revocaciones. ADR-0015. Habeas Data: nunca hard-delete; status FSM transitions only.';

COMMENT ON COLUMN public.conversation_carts.discount_cents IS
'Snapshot del descuento aplicado por cupón activo. Para free_shipping puede mutar con re-cotización shipping (ADR-0015 D2).';
