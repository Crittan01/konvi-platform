-- Migración: campo visión del negocio
ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS vision TEXT;

COMMENT ON COLUMN public.tenants.vision IS
  'Visión del negocio (max 280 chars). Dónde quiere llegar la empresa. Opcional.';
