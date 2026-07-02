-- F2 (roadmap producción) — jerarquía de categorías Categoría › Subcategoría, per-tenant, 2 niveles.
--
-- ADITIVA · idempotente · nullable · reversible. La RLS 'Tenant Isolation' de product_categories (ya con
-- WITH CHECK tras F0) cubre la columna. Self-FK ON DELETE SET NULL (borrar el padre no borra las subcategorías).
--
-- DECISIÓN (founder, 2026-07-02): el catálogo se organiza en DOS niveles — categoría PADRE (vertical:
-- "Salud y Belleza", "Tecnología") › SUBcategoría (hoja: "Aceites Esenciales", "Audífonos"). Los PRODUCTOS
-- cuelgan de una SUBcategoría (hoja) y heredan su contrato de atributos. Es UN eje operativo (la de marketplace
-- se deriva por categoría, no se captura por producto). Backward-compatible: las categorías planas existentes
-- se vuelven subcategorías de un padre por vertical (data step aparte); los productos quedan intactos.

ALTER TABLE public.product_categories
  ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES public.product_categories(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_product_categories_parent
  ON public.product_categories (tenant_id, parent_id);

COMMENT ON COLUMN public.product_categories.parent_id IS
  'F2: categoría PADRE (jerarquía 2 niveles Categoría›Subcategoría). NULL = raíz (categoría de vertical). '
  'Los productos cuelgan de subcategorías (hojas). Self-FK ON DELETE SET NULL.';
