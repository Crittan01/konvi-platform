-- Modelo de identidad legal del tenant.
--
-- Problema: `public.tenants` no tiene con qué identificar legalmente al negocio. Solo existe
-- `nit` (text, nullable, sin validación) y en la consola está etiquetado literalmente "NIT / CC"
-- — un campo ambiguo para dos identificadores distintos. NO existe: razón social (el `name` es
-- la marca comercial, p. ej. "KAIU Living Natural"), tipo de persona (natural/jurídica), tipo y
-- número de documento por separado, dígito de verificación, régimen de IVA, ni domicilio.
--
-- Consecuencias reales (no teóricas):
--   1. HABEAS DATA (Ley 1581 / Decreto 1377): el aviso de privacidad debe identificar al
--      RESPONSABLE DEL TRATAMIENTO con nombre/razón social, NIT, domicilio y canal de derechos.
--      Hoy `apps/web/public/docs/legal/privacy-policy.md` es un template con placeholders
--      ([Nombre del Tenant], NIT: [XXX], Dirección: [XXX]) porque NO HAY DATOS que poner.
--   2. LEY 1480 (Estatuto del Consumidor): el vendedor debe ser identificable por el comprador.
--   3. FISCAL: si/cuando aplique la obligación de facturar, se necesita razón social, documento
--      con DV, régimen y domicilio. La obligación depende de la forma jurídica y los ingresos
--      (decisión del contador del tenant) — este modelo la habilita sin presuponerla.
--
-- Diseño: TODO aditivo y nullable. No rompe tenants existentes ni el flujo actual. `nit` se
-- CONSERVA (lo consume el system prompt del bot y la consola) y se backfillea a `doc_numero`.
-- La consola es la que exigirá completitud antes del lanzamiento, no la DB.

ALTER TABLE public.tenants
  -- Naturaleza jurídica: determina qué documento aplica y qué obligaciones fiscales rigen.
  ADD COLUMN IF NOT EXISTS tipo_persona text,
  -- Nombre legal. Para persona jurídica: la razón social del certificado de existencia.
  -- Para persona natural: nombres y apellidos completos como figuran en el documento.
  -- Es DISTINTO de `name`, que es la marca comercial de cara al cliente.
  ADD COLUMN IF NOT EXISTS razon_social text,
  -- Documento de identificación, desagregado (antes: todo mezclado en `nit`).
  ADD COLUMN IF NOT EXISTS doc_tipo text,
  ADD COLUMN IF NOT EXISTS doc_numero text,
  ADD COLUMN IF NOT EXISTS doc_dv text,          -- dígito de verificación (solo NIT)
  -- Régimen de IVA. Es lo que define el umbral de 3.500 UVT (Art. 437 ET) — y es INDEPENDIENTE
  -- de la obligación de facturar (Concepto DIAN 106/2022). Se registra como dato, no como regla.
  ADD COLUMN IF NOT EXISTS regimen_iva text,
  -- Domicilio: lo exige el aviso de privacidad y la identificación del vendedor.
  ADD COLUMN IF NOT EXISTS domicilio_direccion text,
  ADD COLUMN IF NOT EXISTS domicilio_ciudad text,
  ADD COLUMN IF NOT EXISTS domicilio_departamento text,
  ADD COLUMN IF NOT EXISTS domicilio_pais text NOT NULL DEFAULT 'CO',
  -- Canal para que el TITULAR ejerza sus derechos (acceso, rectificación, supresión).
  -- Puede diferir del email comercial: el aviso exige uno que alguien efectivamente lea.
  ADD COLUMN IF NOT EXISTS email_habeas_data text;

-- Dominios cerrados (fail-fast ante datos inválidos, permitiendo NULL mientras no se complete).
ALTER TABLE public.tenants DROP CONSTRAINT IF EXISTS tenants_tipo_persona_check;
ALTER TABLE public.tenants ADD CONSTRAINT tenants_tipo_persona_check
  CHECK (tipo_persona IS NULL OR tipo_persona IN ('natural', 'juridica'));

ALTER TABLE public.tenants DROP CONSTRAINT IF EXISTS tenants_doc_tipo_check;
ALTER TABLE public.tenants ADD CONSTRAINT tenants_doc_tipo_check
  CHECK (doc_tipo IS NULL OR doc_tipo IN ('NIT', 'CC', 'CE', 'PAS'));

ALTER TABLE public.tenants DROP CONSTRAINT IF EXISTS tenants_regimen_iva_check;
ALTER TABLE public.tenants ADD CONSTRAINT tenants_regimen_iva_check
  CHECK (regimen_iva IS NULL OR regimen_iva IN ('responsable', 'no_responsable'));

-- Backfill conservador: el `nit` existente pasa a `doc_numero` (sin inferir el tipo de persona
-- ni el tipo de documento — eso lo confirma el tenant en la consola, no lo adivinamos).
UPDATE public.tenants
SET doc_numero = btrim(nit)
WHERE doc_numero IS NULL AND nit IS NOT NULL AND btrim(nit) <> '';

COMMENT ON COLUMN public.tenants.tipo_persona IS
  'natural | juridica. Determina el documento aplicable y las obligaciones fiscales (la aplicabilidad la confirma el contador del tenant).';
COMMENT ON COLUMN public.tenants.razon_social IS
  'Nombre LEGAL (razón social o nombres y apellidos). Distinto de `name`, que es la marca comercial.';
COMMENT ON COLUMN public.tenants.doc_dv IS
  'Dígito de verificación del NIT. Solo aplica a doc_tipo = NIT.';
COMMENT ON COLUMN public.tenants.regimen_iva IS
  'responsable | no_responsable (Art. 437 ET, umbral 3.500 UVT). Dato informativo: NO determina por sí solo la obligación de facturar.';
COMMENT ON COLUMN public.tenants.email_habeas_data IS
  'Canal para que el titular ejerza derechos (Ley 1581). Puede diferir del email comercial.';
COMMENT ON COLUMN public.tenants.nit IS
  'LEGADO: identificador mezclado (NIT o CC). Reemplazado por doc_tipo + doc_numero + doc_dv. Se conserva porque lo consume el system prompt del bot; migrar consumidores y retirar.';
