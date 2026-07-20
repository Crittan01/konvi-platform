-- Perf Wave 4 (audit perf-rebaseline 2026-07-19 · rank 2, mayor impacto) — índice del
-- FK del embed de catálogo.
--
-- get_tenant_catalog (services/ai-orchestrator/tools/catalog_tool.py:74-85) carga el catálogo
-- del turno agentic vía embed PostgREST:
--   products.select("id, ..., product_variations(id, sku, attributes, price, stock_quantity)")
--        .eq("tenant_id", X).eq("status","active")
-- PostgREST resuelve el embed por el FK product_variations.product_id → products.id. La tabla
-- product_variations solo tiene PK (id) + UNIQUE (tenant_id, sku) — NINGÚN índice sobre product_id,
-- así que el lookup del embed degrada a seq scan a medida que crece el catálogo por tenant.
-- Indexar la columna FK es práctica estándar de Postgres (los FK NO auto-crean índice).
--
-- NOTA DE APLICACIÓN: en KAIU (tabla pequeña) el CREATE es instantáneo. Si en el futuro la tabla
-- es grande y hay tráfico de escritura, aplicar como
--   CREATE INDEX CONCURRENTLY ...   (fuera de transacción, evita el lock de escritura durante el build).
-- Mismo criterio que 20260703140000_f14_idx_conversations_tenant_phone.sql.

CREATE INDEX IF NOT EXISTS idx_product_variations_product
  ON public.product_variations (product_id);
