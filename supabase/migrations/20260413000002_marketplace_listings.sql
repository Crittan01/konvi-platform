-- =============================================================================
-- Marketplace Listings
-- Conecta Variaciones (Supabase) con Anuncios (Mercado Libre, Shopify, etc.)
-- =============================================================================

CREATE TABLE public.marketplace_listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    variation_id    UUID NOT NULL REFERENCES public.product_variations(id) ON DELETE CASCADE,
    
    external_id     TEXT NOT NULL,
    provider        TEXT NOT NULL DEFAULT 'mercadolibre', -- 'mercadolibre', 'shopify', etc.
    status          TEXT NOT NULL DEFAULT 'active',       -- 'active', 'paused', 'closed'
    external_price  NUMERIC,
    external_url    TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- No tenant should have the same external variation ID mapped twice
    UNIQUE(tenant_id, provider, external_id),
    -- One variation can only map to one ML listing
    UNIQUE(tenant_id, provider, variation_id)
);

-- RLS Policies
ALTER TABLE public.marketplace_listings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation_marketplace" 
    ON public.marketplace_listings 
    FOR ALL 
    USING (tenant_id = (SELECT auth.uid()));

CREATE OR REPLACE FUNCTION update_marketplace_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger update_at
CREATE TRIGGER set_marketplace_listings_updated_at
BEFORE UPDATE ON public.marketplace_listings
FOR EACH ROW
EXECUTE FUNCTION update_marketplace_updated_at();
