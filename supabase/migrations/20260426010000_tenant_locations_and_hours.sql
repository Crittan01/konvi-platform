-- Migración: sedes físicas múltiples y horario de atención en tenant

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS store_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS business_hours  TEXT;

COMMENT ON COLUMN public.tenants.store_locations IS
  'Array de sedes físicas: [{name, city, state, street}]';
COMMENT ON COLUMN public.tenants.business_hours IS
  'Horario de atención en texto libre. Ej: Lunes a Viernes 8am-6pm, Sábados 9am-2pm';
