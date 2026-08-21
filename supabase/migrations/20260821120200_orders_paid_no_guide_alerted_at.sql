-- B4 (auditoría money-path 2026-08-21) — marca anti-spam del reconciliador
-- "pagado sin guía".
--
-- Hallazgo: si la generación de guía Aveonline falla tras un pago confirmado,
-- hoy solo hay un logger.warning — el cliente pagó y nadie se entera de que el
-- paquete no tiene guía.
--
-- Fix: el worker corre un reconciliador periódico (default cada 15 min) que lista
-- órdenes `confirmed` con antigüedad >15 min sin shipment con guía
-- (labeled/simulated/en tránsito) y alerta por Telegram al operador del tenant.
-- Esta columna es la marca de "ya alerté esta orden" → UNA sola alerta por orden.
--
-- Forward-only. Idempotente (IF NOT EXISTS).

BEGIN;

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS paid_no_guide_alerted_at TIMESTAMPTZ;

COMMENT ON COLUMN public.orders.paid_no_guide_alerted_at IS
    'B4: timestamp de la alerta Telegram "pagado sin guía" enviada por el '
    'reconciliador del worker (services/ai-orchestrator/worker.py). NULL = no alertada.';

COMMIT;
