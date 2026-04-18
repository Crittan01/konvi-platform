-- =============================================================================
-- Agregar dirección de entrega a contacts
-- Permite pre-llenar destino en cotización de envío desde el pedido del contacto.
-- Estructura: { street, number?, city, state, country, dane_code }
-- =============================================================================

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS address JSONB;
