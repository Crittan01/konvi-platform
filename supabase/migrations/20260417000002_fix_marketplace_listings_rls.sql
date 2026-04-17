-- Fix RLS policy on marketplace_listings.
-- Original policy used auth.uid() as tenant_id — incorrect for this multi-tenant model
-- where tenant_id comes from app_metadata.tenant_id, not from auth.uid().

DROP POLICY IF EXISTS "tenant_isolation_marketplace" ON public.marketplace_listings;

CREATE POLICY "tenant_isolation_marketplace"
    ON public.marketplace_listings
    FOR ALL
    USING (
        tenant_id = (
            SELECT (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
        )
    );
