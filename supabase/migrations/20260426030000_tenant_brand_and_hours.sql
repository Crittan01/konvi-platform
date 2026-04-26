-- Migración: Filosofía de marca + horario estructurado en tenant
-- Permite al bot conocer la misión, valores, tono y horario de soporte del negocio.

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS mision              TEXT,
  ADD COLUMN IF NOT EXISTS valores             TEXT,
  ADD COLUMN IF NOT EXISTS tono_comunicacion   TEXT NOT NULL DEFAULT 'amigable',
  ADD COLUMN IF NOT EXISTS support_schedule    JSONB,
  ADD COLUMN IF NOT EXISTS after_hours_message TEXT,
  ADD COLUMN IF NOT EXISTS cutoff_message      TEXT;

ALTER TABLE public.tenants
  ADD CONSTRAINT tenants_tono_comunicacion_check
  CHECK (tono_comunicacion IN ('formal', 'amigable', 'cercano', 'profesional', 'juvenil'));

COMMENT ON COLUMN public.tenants.mision IS
  'Propósito del negocio (max 280 chars). Se inyecta en el system prompt del bot.';
COMMENT ON COLUMN public.tenants.valores IS
  'Valores de la marca (max 280 chars). Se inyecta en el system prompt del bot.';
COMMENT ON COLUMN public.tenants.tono_comunicacion IS
  'Tono del bot: formal|amigable|cercano|profesional|juvenil. Ajusta instrucciones al LLM.';
COMMENT ON COLUMN public.tenants.support_schedule IS
  'Horario de soporte humano: {days:[1-7], open:"09:00", close:"18:00"} (TZ: America/Bogota).';
COMMENT ON COLUMN public.tenants.after_hours_message IS
  'Mensaje que el bot envía cuando se solicita asesor fuera del horario de support_schedule.';
COMMENT ON COLUMN public.tenants.cutoff_message IS
  'Mensaje informativo de corte de envíos. Ej: "Pedidos antes de las 2PM salen hoy".';
