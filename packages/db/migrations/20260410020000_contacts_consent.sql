-- Habeas Data Colombia: registrar consentimiento explícito del contacto
-- Ref: Ley 1581 de 2012 — el Responsable del tratamiento (tenant) debe poder demostrar
-- que obtuvo autorización del titular de los datos.
ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS consent_given BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS consent_date  TIMESTAMPTZ;

-- Índice para consultas de auditoría de consentimiento
CREATE INDEX IF NOT EXISTS contacts_consent_idx
  ON public.contacts (tenant_id, consent_given);
