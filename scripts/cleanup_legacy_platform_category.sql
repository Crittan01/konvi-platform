-- F2/coherencia — limpieza de datos legacy: products.platform_category_id (marketplace per-producto).
--
-- ADR-0029 D2: la taxonomía de marketplace se DERIVA por categoría (product_categories.platform_category_id),
-- NO se captura por producto. Tras alinear todo el código (display usa la operativa, el import escribe la
-- operativa, ProductCreate/Patch ya no aceptan el campo), los valores per-producto quedan MUERTOS: ninguna
-- superficie los muestra ni ningún path transaccional los lee (verificado grep vacío). La publicación MeLi
-- usa meli_category_id nativo en marketplace_listings, independiente de esta columna.
--
-- SEGURO: solo pone NULL valores legacy ya invisibles. La columna se conserva (drop = migración de esquema aparte).
-- Ejecutar:  supabase db query --linked -f scripts/cleanup_legacy_platform_category.sql

UPDATE public.products
   SET platform_category_id = NULL
 WHERE platform_category_id IS NOT NULL;

-- Verificación: 0 filas con el campo legacy poblado.
SELECT count(*) AS restantes_con_platform_category_id
FROM public.products
WHERE platform_category_id IS NOT NULL;
