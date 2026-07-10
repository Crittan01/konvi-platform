-- =============================================================================
-- BLOQUE B (item 5) — Idempotencia de generación de guía (anti guía DUPLICADA facturable).
--
-- HALLAZGO (audit + verificado en HEAD): `_generate_shipping_guide_async` llama a
-- Aveonline `generate_guide` (que FACTURA si simulate=False) y PERSISTE el shipment
-- DESPUÉS. No hay guard: una 2ª invocación (webhook Wompi duplicado, retry, cron de
-- reconciliación) factura OTRA guía → cobro duplicado real. No existe UNIQUE por order.
--
-- FIX: patrón claim-before-bill. El código INSERTA una fila `shipments` en estado
-- 'generating' ANTES de facturar. Este índice único parcial garantiza a lo sumo UNA
-- guía activa/generada por (tenant_id, order_id): el 2º INSERT concurrente/retry falla
-- con unique_violation → esa invocación NO factura (idempotente).
--
-- Estados y su relación con el índice:
--   'generating'  → claim en progreso (o excepción ambigua al facturar: la guía PUDO
--                   facturarse en un timeout → queda EN el índice para bloquear auto-retry;
--                   resolución manual del operador). EN el índice.
--   'labeled'     → guía real generada OK. EN el índice.
--   'simulated'   → guía simulada OK (no factura). EN el índice.
--   'pending_generation' → Aveonline respondió NOT-OK (definitivamente NO facturó) →
--                   FUERA del índice → permite reintento seguro.
--   'quoted'      → cotización (no es guía) → FUERA del índice.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. Idempotente
--    (IF NOT EXISTS). PRE-CHECK OBLIGATORIO: si ya existen filas duplicadas
--    (tenant_id, order_id) con status IN ('generating','labeled','simulated') el CREATE
--    fallará — deduplicar antes (conservar la más reciente con tracking_number).
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS shipments_one_active_guide_per_order
    ON public.shipments (tenant_id, order_id)
    WHERE order_id IS NOT NULL
      AND status IN ('generating', 'labeled', 'simulated');

COMMENT ON INDEX public.shipments_one_active_guide_per_order IS
    'BLOQUE B item 5 — idempotencia guía: a lo sumo 1 guía activa/generada por (tenant,order). Soporta claim-before-bill (INSERT generating antes de facturar Aveonline). pending_generation queda fuera → permite retry.';
