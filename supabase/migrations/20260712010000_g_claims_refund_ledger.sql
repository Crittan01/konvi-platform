-- BLOQUE G-2 — Refund ledger: monto reembolsado REAL en reclamos.
--
-- Contexto (revisión adversarial del KPI net-revenue): `claims.requested_amount` es
-- el monto SOLICITADO por el cliente (intención, nullable), no el reembolso ejecutado
-- (que se hace manual en Wompi, desacoplado). Netear el KPI por `requested_amount`
-- sobre-resta en parciales y sobre-ESTIMA cuando el reclamo no trae monto (común en
-- reclamos creados por el bot). Y `updated_at` es fecha inestable (cualquier edición
-- la mueve). Solución: capturar el monto reembolsado real + su fecha, write-once.
--
--   refunded_amount NUMERIC   — pesos realmente reembolsados (lo captura el operador
--                               al marcar el reclamo 'refunded'; API lo exige).
--   refunded_at     TIMESTAMPTZ — instante del reembolso (write-once en la transición
--                               a 'refunded'; estable ante ediciones posteriores).
--
-- El RPC net-revenue (20260712020000) netea por refunded_amount / refunded_at.

ALTER TABLE public.claims
  ADD COLUMN IF NOT EXISTS refunded_amount NUMERIC,
  ADD COLUMN IF NOT EXISTS refunded_at     TIMESTAMPTZ;

-- Backfill best-effort de reclamos ya 'refunded' (histórico): usa los mejores datos
-- disponibles (requested_amount / updated_at). Los reembolsos NUEVOS capturan el
-- monto real vía API. Solo toca filas donde aún no hay ledger (idempotente).
UPDATE public.claims
   SET refunded_amount = COALESCE(refunded_amount, requested_amount),
       refunded_at     = COALESCE(refunded_at, updated_at)
 WHERE status = 'refunded'
   AND (refunded_amount IS NULL OR refunded_at IS NULL);

-- Índice parcial para el agregado de ventas brutas del KPI (gross por tenant +
-- ventana de creación, solo estados con pago reconocido). Espeja el precedente
-- idx_orders_pending_payment_created. Evita escanear todo el histórico del tenant.
CREATE INDEX IF NOT EXISTS idx_orders_paid_created
  ON public.orders (tenant_id, created_at)
  WHERE status IN ('confirmed', 'processing', 'shipped', 'delivered');
