-- Rev. 68 — Tenant: rol de escalación configurable
--
-- Razón: hoy el bot escala con la palabra "asesor" hardcoded. Algunos tenants
-- prefieren "especialista" (servicios profesionales), "consultor" (B2B) o
-- "agente" (call center). Permitir que cada tenant configure el término que
-- mejor refleja su marca, sin tocar código.
--
-- Cambios:
--   - Columna nueva tenants.escalation_role TEXT con CHECK enum cerrado.
--   - Default 'asesor' (mantiene comportamiento actual sin migración de datos).
--   - El orquestador lee este campo y lo usa en sus mensajes de escalación.

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS escalation_role TEXT NOT NULL DEFAULT 'asesor';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tenants_escalation_role_check'
  ) THEN
    ALTER TABLE public.tenants
      ADD CONSTRAINT tenants_escalation_role_check
      CHECK (escalation_role IN ('asesor', 'especialista', 'consultor', 'agente'));
  END IF;
END$$;

COMMENT ON COLUMN public.tenants.escalation_role IS
  'Término que el bot usa al escalar a humano. Valores: asesor (default), especialista, consultor, agente. Configurable en Settings → General → Escalación.';
