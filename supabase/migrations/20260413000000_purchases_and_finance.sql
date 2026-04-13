-- Migration: 20260413000000_purchases_and_finance.sql
-- Goal: Add financial tracking and supply chain CRM

-- 1) Add cost tracking to existing concepts
ALTER TABLE public.product_variations
  ADD COLUMN cost_price numeric(10,2) DEFAULT 0.00;

ALTER TABLE public.order_items
  ADD COLUMN unit_cost numeric(10,2) DEFAULT 0.00;

-- 2) Suppliers table
CREATE TABLE IF NOT EXISTS public.suppliers (
    id uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    name text NOT NULL,
    contact_email text,
    phone text,
    lead_time_days integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenants can manage their suppliers"
    ON public.suppliers FOR ALL
    USING (tenant_id = public.app_current_tenant());

-- 3) Purchase Orders
CREATE TABLE IF NOT EXISTS public.purchase_orders (
    id uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    supplier_id uuid NOT NULL REFERENCES public.suppliers(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ordered', 'in_transit', 'received', 'cancelled')),
    expected_date timestamp with time zone,
    total_amount numeric(10,2) DEFAULT 0.00,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenants can manage their POs"
    ON public.purchase_orders FOR ALL
    USING (tenant_id = public.app_current_tenant());

-- 4) Purchase Order Items
CREATE TABLE IF NOT EXISTS public.purchase_order_items (
    id uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    po_id uuid NOT NULL REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
    variation_id uuid NOT NULL REFERENCES public.product_variations(id) ON DELETE CASCADE,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_cost numeric(10,2) NOT NULL DEFAULT 0.00,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.purchase_order_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenants can manage their PO items"
    ON public.purchase_order_items FOR ALL
    USING (tenant_id = public.app_current_tenant());

-- 5) Expenses
CREATE TABLE IF NOT EXISTS public.expenses (
    id uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    category text NOT NULL CHECK (category IN ('payroll', 'marketing', 'software', 'logistics', 'other')),
    description text NOT NULL,
    amount numeric(10,2) NOT NULL CHECK (amount > 0),
    expense_date timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.expenses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenants can manage their expenses"
    ON public.expenses FOR ALL
    USING (tenant_id = public.app_current_tenant());
