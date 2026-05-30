-- =============================================================================
-- Rev. 108 Fase B — orders.payment_method para COD bot conversacional.
-- Fecha: 2026-05-26
--
-- Contexto: hasta hoy todas las órdenes asumen pago anticipado vía Wompi
-- (crédito). Rev. 108 Fase B activa contraentrega (COD) en el flujo
-- conversacional — el bot pregunta al cliente "¿pagas online o al recibir?"
-- y dispara ramas distintas según respuesta.
--
-- Diseño:
--   • payment_method TEXT con CHECK ENUM ('credit', 'cod').
--   • Default 'credit' → backward-compat 100% (todas órdenes existentes
--     se asumen credit, comportamiento idéntico al previo).
--   • Sin NOT NULL para migración soft — caller debe setearlo explícito
--     en órdenes nuevas. App layer enforce.
--   • Index parcial para queries operativas "COD ledger" (órdenes COD
--     pending liquidación).
--
-- Reversibilidad: si Fase B se cancela, DROP COLUMN reversible sin
-- pérdida (todas filas existentes asumen credit por default).
-- =============================================================================

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS payment_method TEXT
    CHECK (payment_method IN ('credit', 'cod')) DEFAULT 'credit';

COMMENT ON COLUMN public.orders.payment_method IS
    'Modalidad de pago: credit=Wompi anticipado (default), cod=contraentrega
     (courier recauda al entregar). Rev. 108 Fase B. Determina ramificación
     del flujo en payment_link_tool + _generate_shipping_guide.';

-- Backfill explícito (idempotente) — toda fila previa = 'credit'.
UPDATE public.orders SET payment_method = 'credit' WHERE payment_method IS NULL;

-- Index parcial para queries operativas COD (Inbox filter + ledger).
CREATE INDEX IF NOT EXISTS orders_cod_pending_idx
    ON public.orders (tenant_id, created_at DESC)
    WHERE payment_method = 'cod';

NOTIFY pgrst, 'reload schema';
