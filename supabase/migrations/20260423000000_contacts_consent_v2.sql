-- Bloque C: Campos de consentimiento Ley 1581 + soft-delete para retención
-- Aplica a contacts

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS consent_given_at     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS consent_channel      TEXT DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS consent_text_version TEXT,
  ADD COLUMN IF NOT EXISTS deleted_at           TIMESTAMPTZ;  -- soft-delete para retención

-- Índice para purge job (contactos eliminados sin órdenes después de 30 días)
CREATE INDEX IF NOT EXISTS idx_contacts_deleted_at
  ON contacts (tenant_id, deleted_at)
  WHERE deleted_at IS NOT NULL;

-- Poblar consent_given_at retroactivamente donde ya existe consentimiento
UPDATE contacts
SET consent_given_at = COALESCE(consent_date, created_at)
WHERE consent_given = true AND consent_given_at IS NULL;

-- Poblar consent_channel retroactivamente
UPDATE contacts
SET consent_channel = COALESCE(consent_source, 'manual')
WHERE consent_channel IS NULL;
