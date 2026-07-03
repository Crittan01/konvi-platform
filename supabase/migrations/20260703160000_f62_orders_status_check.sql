-- F62 (audit fullstack-review-2026-07-03 · HIGH) — CHECK de estados de orden (defense-in-depth).
--
-- orders.status es TEXT sin CHECK constraint (20260424200000_wompi_payments_phase_c.sql:10). El backend
-- usa 7 estados (orders.py VALID_STATUSES). La verificación adversarial confirmó que TODOS los writers de
-- orders.status (orders.py, wompi_webhook, meli_webhook MELI_*_STATUS_MAP, cart_tool, order_cancellation,
-- worker, orchestrator) mapean a los mismos 7 valores → el CHECK no rechaza ningún escritor actual.
--
-- NOT VALID: agrega el constraint SIN escanear/validar las filas existentes (rápido, sin lock de scan). Las
-- filas NUEVAS sí se validan. Para validar las existentes más tarde (cuando convenga):
--   ALTER TABLE public.orders VALIDATE CONSTRAINT orders_status_check;
--
-- DROP IF EXISTS previo = idempotente (re-ejecutable pese al drift del ledger).

ALTER TABLE public.orders DROP CONSTRAINT IF EXISTS orders_status_check;

ALTER TABLE public.orders ADD CONSTRAINT orders_status_check
  CHECK (status IN ('pending','pending_payment','confirmed','processing','shipped','delivered','cancelled'))
  NOT VALID;
