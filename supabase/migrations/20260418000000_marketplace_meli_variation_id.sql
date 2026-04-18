-- Migración: mapping variación MeLi en marketplace_listings
-- Contexto: MeLi items con variaciones propias (talla, color, etc.) requieren
-- especificar el ID de la variación MeLi al hacer PUT /items/{id}.
-- NULL = item MeLi sin variaciones (caso simple, comportamiento previo)
-- NOT NULL = variación MeLi específica vinculada a esta variante Supabase

ALTER TABLE marketplace_listings
  ADD COLUMN IF NOT EXISTS meli_variation_id BIGINT DEFAULT NULL;

COMMENT ON COLUMN marketplace_listings.meli_variation_id IS
  'ID de variación MeLi (variations[].id). NULL para items sin variaciones propias en MeLi.';
