-- ADR-0027 Pieza 1 — Categorías de catálogo como DATO DE PRIMERA CLASE, POR TENANT.
--
-- Contexto: hoy la "categoría" de un producto se DERIVA por heurística ("primera
-- palabra del título") en 3 lugares duplicados (system_prompt.py, agentic/tools/catalog.py,
-- y _CATEGORIES hardcodeadas a la vertical KAIU en cart_render_coherence.py). Eso NO es
-- multi-tenant: un tenant de moda/alimentos cae a categorías falsas. Esta migración crea el
-- modelo per-tenant que reemplaza la heurística y habilita el catálogo navegable (índice de
-- categorías + paginación + búsqueda) en vez del volcado O(N) en el prompt.
--
-- FASE EXPAND: 100% ADITIVA, NULLABLE, IDEMPOTENTE. NO hace backfill (eso va en un script
-- aparte, re-ejecutable) ni toca platform_categories/platform_category_id (limpieza CONTRACT
-- futura). El código tiene fallback título-head cuando category_id IS NULL → cero regresión
-- durante la transición. Reversible: UPDATE products SET category_id=NULL deshace el efecto.
--
-- NO reutiliza platform_categories: esa tabla es GLOBAL (UNIQUE(name), sin tenant_id, RLS
-- read-only) — taxonomía de plataforma, no "las categorías de ESTE tenant".

-- 1) Tabla de categorías por tenant.
CREATE TABLE IF NOT EXISTS public.product_categories (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,                  -- clave normalizada (ej. "jabon")
  display_label TEXT,                            -- etiqueta visible (ej. "Jabones Artesanales")
  sort_order    INT  NOT NULL DEFAULT 0,         -- orden en el índice que ve el cliente
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_product_categories_tenant
  ON public.product_categories (tenant_id, sort_order);

ALTER TABLE public.product_categories ENABLE ROW LEVEL SECURITY;
-- RLS espejo de products (ADR-0025 GUC). Idempotente: drop+create.
DROP POLICY IF EXISTS "Tenant Isolation" ON public.product_categories;
CREATE POLICY "Tenant Isolation" ON public.product_categories
  FOR ALL USING (tenant_id = public.app_current_tenant())
  WITH CHECK (tenant_id = public.app_current_tenant());

-- 2) Columna de categoría en products (FK nullable, aditiva — no rompe inserts ni queries).
ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS category_id UUID NULL
    REFERENCES public.product_categories(id) ON DELETE SET NULL;

-- 3) Índice para listados/paginación por categoría (solo productos activos del tenant).
CREATE INDEX IF NOT EXISTS idx_products_tenant_category_active
  ON public.products (tenant_id, category_id) WHERE status = 'active';

COMMENT ON TABLE public.product_categories IS
  'ADR-0027 Pieza 1: categorías de catálogo POR TENANT (data-driven). Reemplaza la heurística '
  '"primera palabra del título". Consumida por el índice de categorías, list_catalog, '
  'search_products y el invariant de completitud (CASE D).';
COMMENT ON COLUMN public.products.category_id IS
  'ADR-0027 Pieza 1: categoría del producto (FK a product_categories, per-tenant). NULL → '
  'fallback título-head con log.warning durante el backfill (NO permanente).';
