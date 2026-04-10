-- Add configurable low-stock threshold per tenant (default: 5 units)
ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER NOT NULL DEFAULT 5;
