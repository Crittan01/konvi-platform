-- Migración: Tipo de tienda y redes sociales en tenant
-- Permite que el bot responda correctamente sobre ubicación física, virtual y redes.

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS store_type   TEXT NOT NULL DEFAULT 'fisica',
  ADD COLUMN IF NOT EXISTS social_links JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.tenants
  ADD CONSTRAINT tenants_store_type_check
  CHECK (store_type IN ('fisica', 'virtual', 'fisica_virtual'));

COMMENT ON COLUMN public.tenants.store_type IS
  'Tipo de operación: fisica | virtual | fisica_virtual';
COMMENT ON COLUMN public.tenants.social_links IS
  'Links de redes sociales: {instagram, facebook, tiktok, youtube, website}';

-- Normalizar customer_phone en conversaciones históricas (quitar +)
UPDATE public.conversations
SET customer_phone = LTRIM(customer_phone, '+')
WHERE customer_phone LIKE '+%';

-- Normalizar phone en contactos históricos
UPDATE public.contacts
SET phone = LTRIM(phone, '+')
WHERE phone LIKE '+%';
