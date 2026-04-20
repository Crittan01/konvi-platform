-- =============================================================================
-- Campos de sync pull MeLi en marketplace_listings
-- Permite almacenar datos traídos desde MeLi sin depender de llamadas en tiempo real.
-- Se actualizan vía webhook 'items', sync manual y link/import.
-- =============================================================================

ALTER TABLE public.marketplace_listings
  ADD COLUMN IF NOT EXISTS meli_title       TEXT,
  ADD COLUMN IF NOT EXISTS meli_thumbnail   TEXT,
  ADD COLUMN IF NOT EXISTS meli_condition   TEXT,        -- 'new' | 'used' | 'not_specified'
  ADD COLUMN IF NOT EXISTS meli_category_id TEXT,
  ADD COLUMN IF NOT EXISTS meli_attributes  JSONB,
  ADD COLUMN IF NOT EXISTS synced_at        TIMESTAMPTZ; -- última vez que se hizo pull desde MeLi
