-- Migración: Creación de la tabla de reclamos (claims)
-- Tipo de sistema: Tracking/Ticket (Sin afectación directa a cash flow)

CREATE TABLE public.claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    customer_id UUID REFERENCES public.contacts(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open', -- 'open', 'investigating', 'resolved', 'rejected'
    reason TEXT NOT NULL, -- 'defective', 'wrong_item', 'delayed', 'other'
    requested_amount NUMERIC, 
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS: Permite que el tenant vea solo sus propios reclamos
ALTER TABLE public.claims ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants can view own claims" 
ON public.claims FOR SELECT 
TO authenticated 
USING (tenant_id = (current_setting('app.current_tenant_id', true))::uuid);

CREATE POLICY "Tenants can insert own claims" 
ON public.claims FOR INSERT 
TO authenticated 
WITH CHECK (tenant_id = (current_setting('app.current_tenant_id', true))::uuid);

CREATE POLICY "Tenants can update own claims" 
ON public.claims FOR UPDATE 
TO authenticated 
USING (tenant_id = (current_setting('app.current_tenant_id', true))::uuid)
WITH CHECK (tenant_id = (current_setting('app.current_tenant_id', true))::uuid);

CREATE POLICY "Tenants can delete own claims" 
ON public.claims FOR DELETE 
TO authenticated 
USING (tenant_id = (current_setting('app.current_tenant_id', true))::uuid);

-- Trigger de updated_at
CREATE OR REPLACE FUNCTION update_claims_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_claims_updated_at
BEFORE UPDATE ON public.claims
FOR EACH ROW EXECUTE FUNCTION update_claims_updated_at();

-- Índices de búsqueda y filtro
CREATE INDEX idx_claims_tenant_id ON public.claims(tenant_id);
CREATE INDEX idx_claims_order_id ON public.claims(order_id);
CREATE INDEX idx_claims_status ON public.claims(status);
