-- =============================================================================
-- Rev. 103 — shipping_phone defaultea al WhatsApp.
--
-- Decisión UX: cuando el cliente NO menciona un celular alternativo de
-- envío, contacts.shipping_phone debe quedar en el mismo número del
-- WhatsApp (contacts.phone) para que la transportadora siempre tenga un
-- número de contacto. Solo cuando el cliente da explícitamente otro
-- ("el pedido lo recibe mi mamá, su celular es 322...") sobrescribe el
-- valor.
--
-- Cambios:
--   1. Backfill: filas con shipping_phone NULL/'' → phone.
--   2. Trigger BEFORE INSERT/UPDATE: si shipping_phone NULL/'' al final
--      de la operación, copiar phone. Idempotente y defensivo contra
--      cualquier caller (orchestrator, dashboard, MeLi import, futuros).
-- =============================================================================

-- 1) Backfill — filas existentes sin shipping_phone.
UPDATE public.contacts
   SET shipping_phone = phone
 WHERE phone IS NOT NULL
   AND (shipping_phone IS NULL OR btrim(shipping_phone) = '');

-- 2) Trigger function — defaultea al phone si shipping_phone queda vacío.
CREATE OR REPLACE FUNCTION public.contacts_default_shipping_phone()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.shipping_phone IS NULL OR btrim(NEW.shipping_phone) = '' THEN
        NEW.shipping_phone := NEW.phone;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_contacts_default_shipping_phone ON public.contacts;

CREATE TRIGGER trg_contacts_default_shipping_phone
    BEFORE INSERT OR UPDATE OF phone, shipping_phone ON public.contacts
    FOR EACH ROW
    EXECUTE FUNCTION public.contacts_default_shipping_phone();

COMMENT ON TRIGGER trg_contacts_default_shipping_phone ON public.contacts IS
    'Rev. 103 — shipping_phone defaultea a phone (WhatsApp) cuando viene NULL/empty.';
