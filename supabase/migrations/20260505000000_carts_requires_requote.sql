-- Rev. 80 — Flag de re-cotización requerida en conversation_carts.
--
-- Contexto: cuando el cart-en-DB es source of truth (rev. 80), el cliente
-- puede modificar items (cambiar cantidad / agregar / quitar) DESPUÉS de
-- que el bot ya cotizó el envío. Sin un mecanismo de invalidación, el
-- shipping_cents queda desactualizado y le cobramos lo incorrecto.
--
-- Política:
--   • Triggers en cart_tool.py setean requires_requote=true cuando un
--     item cambia (add/update/remove).
--   • set_shipping_meta lo retorna a false cuando se persiste una rate.
--   • El bot detecta requires_requote=true antes del resumen y obliga a
--     re-cotizar.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS.

ALTER TABLE public.conversation_carts
  ADD COLUMN IF NOT EXISTS requires_requote BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.conversation_carts.requires_requote IS
  'Rev. 80: flag activado cuando los items cambian post-cotización. El bot debe re-cotizar antes del resumen.';
