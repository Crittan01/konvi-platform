-- =============================================================================
-- Rev. 108 Fase B — conversation_carts.payment_method (intent del cart).
-- Fecha: 2026-05-26
--
-- Contexto: detector pre-LLM cod_intent_resolver marca el cart cuando el
-- cliente menciona "contraentrega" / "pago al recibir". Esta marca viaja
-- con el cart hasta que se cree la orden, momento en que se copia a
-- orders.payment_method (migración 20260531000000).
--
-- Diseño:
--   • TEXT con CHECK ENUM ('credit', 'cod').
--   • Default 'credit' → backward-compat 100%.
--   • Sin NOT NULL — backfill explícito.
--
-- Flujo de datos:
--   1. Cliente: "voy a pagar contra entrega"
--   2. dispatcher detecta intent → UPDATE cart.payment_method='cod'
--   3. shipping_quote_tool lee cart.payment_method → filtra carriers
--      supports_cod=true del tenant
--   4. payment_link_tool lee cart.payment_method → bypass Wompi si 'cod'
--   5. orders se crea con payment_method = cart.payment_method
--
-- Reversibilidad: DROP COLUMN reversible. Si Fase B se pausa, sin
-- pérdida porque default 'credit' replica comportamiento previo.
-- =============================================================================

ALTER TABLE public.conversation_carts
    ADD COLUMN IF NOT EXISTS payment_method TEXT
    CHECK (payment_method IN ('credit', 'cod')) DEFAULT 'credit';

COMMENT ON COLUMN public.conversation_carts.payment_method IS
    'Intent de modalidad pago del cliente: credit=Wompi (default),
     cod=contraentrega. Marcado por cod_intent_resolver pre-LLM cuando
     el cliente lo solicita explícitamente. Se copia a orders.payment_method
     al cierre del cart.';

UPDATE public.conversation_carts SET payment_method = 'credit' WHERE payment_method IS NULL;

NOTIFY pgrst, 'reload schema';
