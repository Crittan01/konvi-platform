-- F1 (roadmap producción 2026-07-02) — coherencia de DINERO: snapshot del descuento en la orden.
--
-- ADITIVA · idempotente · NOT NULL DEFAULT 0 (Postgres aplica el default a filas existentes sin reescribir).
-- La RLS 'Tenant Isolation' de orders (ya con WITH CHECK tras F0) cubre la columna.
--
-- PROBLEMA (auditoría, CRÍTICO de dinero): el descuento del cupón se calcula en conversation_carts.discount_cents
-- pero orders.py recompone total_amount = Σ(unit_price*qty) + shipping_cost IGNORANDO el descuento → el cliente
-- ve un total con descuento y Wompi cobra el total PLENO. La orden no tenía dónde snapshotear el descuento.
--
-- Convención verificada: orders.total_amount y shipping_cost son numeric(10,2) en MONEDA (no cents). discount_amount
-- sigue esa convención. Coherencia objetivo: total_amount = max(0, subtotal_productos - discount_amount) + shipping_cost.

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS discount_amount numeric(10,2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.orders.discount_amount IS
  'F1: descuento del cupón snapshoteado en la orden (moneda, numeric(10,2), consistente con total_amount/shipping_cost). '
  'total_amount = max(0, subtotal_productos - discount_amount) + shipping_cost. El cobro Wompi usa total_amount.';
