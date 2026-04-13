-- 20260413000001_finance_polish.sql
-- Fix cascading deletes to preserve historic financial integrity

-- 1. Modify purchase_orders.supplier_id to SET NULL instead of CASCADE
ALTER TABLE public.purchase_orders
  DROP CONSTRAINT IF EXISTS purchase_orders_supplier_id_fkey;

ALTER TABLE public.purchase_orders
  ADD CONSTRAINT purchase_orders_supplier_id_fkey
  FOREIGN KEY (supplier_id)
  REFERENCES public.suppliers(id)
  ON DELETE SET NULL;

-- 2. Modify purchase_order_items.variation_id to SET NULL instead of CASCADE
ALTER TABLE public.purchase_order_items
  DROP CONSTRAINT IF EXISTS purchase_order_items_variation_id_fkey;

ALTER TABLE public.purchase_order_items
  ADD CONSTRAINT purchase_order_items_variation_id_fkey
  FOREIGN KEY (variation_id)
  REFERENCES public.product_variations(id)
  ON DELETE SET NULL;
