-- ============================================================================
-- Contacts: add email column
-- Date: 2026-04-24
--
-- Email del contacto, recolectado en flujo conversacional de compra.
-- Opcional (puede comprarse sin email), pero recomendado para notificaciones
-- y pre-fill del formulario de pago Wompi.
-- ============================================================================

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS email TEXT;

CREATE INDEX IF NOT EXISTS idx_contacts_email
  ON public.contacts(tenant_id, email)
  WHERE email IS NOT NULL;
