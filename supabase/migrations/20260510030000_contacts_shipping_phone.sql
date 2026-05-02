-- =============================================================================
-- Rev. 103 — Phone alternativo para envío (separado del WhatsApp).
--
-- Caso de uso: hijo compra para mamá. WhatsApp = phone hijo (titular pago);
-- shipping_phone = phone mamá (transportadora la contacta para entrega).
--
-- Reglas:
--   • shipping_phone OPCIONAL. Si null, Envía usa contacts.phone (default).
--   • contacts.phone NUNCA se sobrescribe por shipping_phone (invariante:
--     contacts.phone == handle WhatsApp == titular pago).
--   • Wompi recibe contacts.phone (titular pago = canal chat).
--   • Envía usa shipping_phone if not null else contacts.phone.
-- =============================================================================

ALTER TABLE public.contacts
    ADD COLUMN IF NOT EXISTS shipping_phone TEXT;

COMMENT ON COLUMN public.contacts.shipping_phone IS
    'Rev. 103: Phone alternativo para envío (transportadora). Si null, '
    'usar contacts.phone. NO cambia el handle WhatsApp ni el titular pago.';
