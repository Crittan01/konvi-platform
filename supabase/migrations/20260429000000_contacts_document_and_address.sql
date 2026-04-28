-- Rev. 68 — Contactos: documento de identidad + schema canónico de address
--
-- Razón: el bot conversacional debe llevar al cliente hasta un Payment Link Wompi
-- pre-poblado con customer_data (legal_id + legal_id_type) y un envío Envia con
-- district (barrio). Hoy `contacts` no captura ninguno de los dos. Sin estos
-- datos, el cliente debe re-tipear todo en el checkout (riesgo de abandono) y
-- los carriers que exigen barrio rechazan la cotización.
--
-- Cambios:
--   - Columnas nuevas: document_type (CHECK enum Wompi CO) + document_number
--   - CHECK constraint compatible con valores Wompi para Colombia.
--   - Index parcial para búsqueda por documento (solo cuando number IS NOT NULL).
--   - Schema canónico de address JSONB documentado (sin migrar datos existentes).

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS document_type   TEXT,
  ADD COLUMN IF NOT EXISTS document_number TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'contacts_document_type_check'
  ) THEN
    ALTER TABLE public.contacts
      ADD CONSTRAINT contacts_document_type_check
      CHECK (document_type IS NULL OR document_type IN ('CC','CE','NIT','PP','TI','OTHER'));
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_contacts_tenant_document
  ON public.contacts (tenant_id, document_type, document_number)
  WHERE document_number IS NOT NULL;

COMMENT ON COLUMN public.contacts.document_type IS
  'Tipo de documento de identidad. Valores Wompi customer_data.legal_id_type para Colombia: CC, CE, NIT, PP, TI, OTHER.';

COMMENT ON COLUMN public.contacts.document_number IS
  'Número de documento sin formato (sin puntos ni espacios). Validación por tipo en aplicación.';

-- Schema canónico de address JSONB (rev. 68) — documentado para guiar la aplicación.
-- No requiere ALTER (JSONB es flexible); pero el COMMENT sirve de contrato.
COMMENT ON COLUMN public.contacts.address IS
  'Dirección estructurada JSONB. Schema canónico rev. 68:
  {
    "street": "Calle 10 # 5-23",         -- requerido
    "number": "401",                     -- opcional
    "neighborhood": "Chapinero",         -- requerido (barrio para Envia district)
    "city": "Bogotá",                    -- requerido
    "state": "DC",                       -- requerido (código corto)
    "dane_code": "11001000",             -- requerido (DANE 8 dígitos)
    "country": "CO",                     -- default "CO"
    "building_type": "edificio",         -- "casa" | "edificio" | "conjunto"
    "tower": "Torre 3",                  -- opcional, solo conjunto
    "apartment": "401",                  -- opcional, edificio o conjunto
    "complex_name": "Torres del Parque", -- opcional, edificio o conjunto
    "reference": "Frente al parque"      -- opcional
  }
  Campos requeridos según building_type:
    casa     -> street, neighborhood, city, state, dane_code
    edificio -> + apartment
    conjunto -> + tower, apartment';
