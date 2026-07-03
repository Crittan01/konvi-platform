-- FASE 1 compliance (audit F116 · HIGH) — sincroniza consent_given_at con consent_date.
--
-- La migración 20260423000000_contacts_consent_v2 añadió consent_given_at (columna v2 que lee el export
-- legal SAR/SIC) con backfill one-shot, pero NO sincronizó los writers: create_contact, _apply_consent_patch
-- (dashboard) y meli_webhook escribían SOLO consent_date → todo contacto creado/consentido después vía
-- dashboard o MeLi quedó con consent_given=true y consent_given_at NULL → "Otorgado en" vacío en el reporte
-- Habeas Data. Los 3 writers ya se corrigieron en código (escriben ambas columnas). Este backfill arregla
-- las filas históricas ya divergidas. Idempotente (solo toca las que están NULL).
--
-- Follow-up expand-contract (futuro): consolidar en una sola columna (dropear consent_date tras migrar la UI).

UPDATE public.contacts
SET consent_given_at = COALESCE(consent_given_at, consent_date)
WHERE consent_given = true
  AND consent_given_at IS NULL;
