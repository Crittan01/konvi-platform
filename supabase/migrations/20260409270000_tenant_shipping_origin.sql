-- Migration: tenant_shipping_origin
-- Fecha: 2026-04-09
-- Propósito: Añade shipping_origin JSONB a tenants para la dirección de origen
--            de envíos (usada como default en cotizaciones de Envia).
--            También añade logo_url TEXT para branding del tenant en la consola.

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS shipping_origin JSONB,
  ADD COLUMN IF NOT EXISTS logo_url TEXT;

COMMENT ON COLUMN public.tenants.shipping_origin IS
  'Dirección de origen para envíos Envia. '
  'Estructura: {name, company, street, city, state, postal_code, country, phone}';

COMMENT ON COLUMN public.tenants.logo_url IS
  'URL del logo del tenant en Supabase Storage (bucket tenant-branding). '
  'Se muestra en el sidebar de la Tenant Console.';
