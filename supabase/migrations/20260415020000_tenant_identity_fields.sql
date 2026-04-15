-- Migration: tenant_identity_fields
-- Adds NIT, contact email, and contact phone to tenants table

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS nit           TEXT,
  ADD COLUMN IF NOT EXISTS email_contacto TEXT,
  ADD COLUMN IF NOT EXISTS telefono_contacto TEXT;

COMMENT ON COLUMN public.tenants.nit               IS 'NIT o razón social del tenant';
COMMENT ON COLUMN public.tenants.email_contacto    IS 'Email de contacto del negocio';
COMMENT ON COLUMN public.tenants.telefono_contacto IS 'Teléfono de contacto del negocio';
