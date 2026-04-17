-- Corrige stock_movements:
--   1. product_id → nullable (el código lo omite; se puede derivar de variation_id)
--   2. Agrega order_id para idempotencia: evita doble-decremento si el webhook llega dos veces

ALTER TABLE public.stock_movements
  ALTER COLUMN product_id DROP NOT NULL;

ALTER TABLE public.stock_movements
  ADD COLUMN IF NOT EXISTS order_id UUID REFERENCES public.orders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_stock_movements_order ON public.stock_movements(order_id)
  WHERE order_id IS NOT NULL;
