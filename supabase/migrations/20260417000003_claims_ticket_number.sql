-- Agrega consecutivo legible por tenant a la tabla claims.
-- ticket_number es secuencial por tenant (no global), empieza en 1.
-- Mostrado en UI como #001, #002, etc.
-- Nota: la función usa MAX + 1; para volúmenes bajos (reclamos) es suficiente.

ALTER TABLE public.claims
  ADD COLUMN IF NOT EXISTS ticket_number INTEGER;

-- Función que asigna el siguiente número para el tenant
CREATE OR REPLACE FUNCTION public.set_claim_ticket_number()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  SELECT COALESCE(MAX(ticket_number), 0) + 1
    INTO NEW.ticket_number
    FROM public.claims
   WHERE tenant_id = NEW.tenant_id;
  RETURN NEW;
END;
$$;

-- Trigger BEFORE INSERT para asignación automática
DROP TRIGGER IF EXISTS trg_claim_ticket_number ON public.claims;
CREATE TRIGGER trg_claim_ticket_number
  BEFORE INSERT ON public.claims
  FOR EACH ROW
  EXECUTE FUNCTION public.set_claim_ticket_number();

-- Backfill de claims existentes (orden por created_at dentro de cada tenant)
UPDATE public.claims c
SET ticket_number = sub.rn
FROM (
  SELECT id,
         ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at) AS rn
    FROM public.claims
) sub
WHERE c.id = sub.id;
