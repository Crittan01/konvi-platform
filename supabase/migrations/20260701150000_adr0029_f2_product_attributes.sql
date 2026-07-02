-- ADR-0029 Frente 2 (auditoría de coherencia del ecosistema, 2026-07-01) — persistencia de VALORES
-- de atributo a nivel PRODUCTO (no-variante).
--
-- ADITIVA · idempotente (IF NOT EXISTS) · DEFAULT '{}' (Postgres aplica el default a filas existentes sin
-- reescribir la tabla) · reversible (DROP COLUMN). La RLS de products (Tenant Isolation via
-- app_current_tenant) ya cubre esta columna — no requiere policy nueva.
--
-- PROBLEMA (auditoría): F0/F1 (20260630120000) creó el CONTRATO de atributos (product_attribute_definitions)
-- pero NO había dónde guardar los VALORES de atributos PRODUCT-LEVEL (is_variant_axis=false): "Ingrediente
-- activo", "Cancelación de ruido", "FPS", "100% puro", "Con flúor". catalog_tool solo leía
-- product_variations.attributes → esos hechos NUNCA llegaban al LLM → el bot los inventaba o decía "no sé",
-- rompiendo la promesa anti-alucinación (D4). Esta columna cierra el hueco.
--
-- Convención: products.attributes = JSONB {label_del_atributo: valor}, ej. {"Ingrediente activo":"Bakuchiol",
-- "FPS":"50","100% puro":"Sí"}. Coherente con la clave-por-label ya usada en product_variations.attributes
-- (F7 normalizará a códigos). Los atributos VARIANT-AXIS (Volumen, Color…) siguen en product_variations.attributes.

ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.products.attributes IS
  'ADR-0029 F2: valores de atributos PRODUCT-LEVEL (no-variante) del contrato de la categoría, ej. '
  '{"Ingrediente activo":"Bakuchiol","FPS":"50"}. El bot los cita como HECHOS estructurados (D4). Validados '
  'contra product_attribute_definitions por la API. Los variant-axis viven en product_variations.attributes.';
