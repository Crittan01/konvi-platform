-- A2 finiquito 2026-06-23 — Hardening shape canónico `contacts.address` rev. 110.
--
-- Contexto: audit live KAIU dev 2026-06-23 confirma 5/5 contactos productivos
-- ya usan `street` (NO `line1`). Este migration es DEFENSIVO + idempotente:
--   1. Backfill `line1 → street` si algún registro residual existiera.
--   2. Eliminar `line1` huérfano si ambos están presentes (street prevalece).
--   3. Documentar shape canónico en COMMENT.
--
-- NO se agrega CHECK constraint duro en esta migración (adversarial review
-- #7): podría romper inserts UAT/dev en tenants no auditados completamente.
-- Se difiere a una migración posterior tras validar 100% del universo
-- productivo.

BEGIN;

-- Paso 1: backfill defensivo line1 → street (solo si line1 existe Y street
-- NO existe). Idempotente: si nadie tiene line1, no toca filas.
UPDATE public.contacts
SET address = jsonb_set(
        address - 'line1',
        '{street}',
        address->'line1'
    ),
    updated_at = COALESCE(updated_at, NOW())
WHERE address IS NOT NULL
  AND address ? 'line1'
  AND NOT (address ? 'street');

-- Paso 2: eliminar line1 huérfano cuando ambos presentes (street es canónico).
UPDATE public.contacts
SET address = address - 'line1',
    updated_at = COALESCE(updated_at, NOW())
WHERE address IS NOT NULL
  AND address ? 'line1'
  AND address ? 'street';

-- Paso 3: actualizar COMMENT con shape canónico rev. 110.
COMMENT ON COLUMN public.contacts.address IS
'Schema canónico contacts.address rev. 110 (A2 finiquito 2026-06-23):
{
  "street": "Calle 10 #5-23",                -- REQUIRED
  "city": "Bogotá",                          -- REQUIRED
  "building_type": "casa|edificio|conjunto|oficina",  -- REQUIRED
  "neighborhood": "Chapinero",               -- requerido residencial
  "state": "Cundinamarca",                   -- requerido shipping/integraciones
  "dane_code": "11001000",                   -- requerido shipping Aveonline
  "country": "CO",                           -- default CO
  "apartment": "401",                        -- requerido edificio/conjunto/oficina
  "tower": "Torre 3",                        -- requerido conjunto
  "floor": "5",                              -- opcional
  "complex_name": "Torres del Parque",       -- opcional
  "reference": "Frente al parque",           -- opcional
  "company_name": "Acme S.A.S."              -- solo si building_type=oficina
}
Source: services/ai-orchestrator/agentic/tools/contact.py::SaveAddressArgs
Migration original: supabase/migrations/20260429000000_contacts_document_and_address.sql';

COMMIT;
