-- F2 (roadmap producción) — DATA seed de tenant (NO es migración de esquema; no va al ledger).
--
-- Aterriza la arquitectura modular multi-vertical del founder sobre el tenant de referencia KAIU
-- (0fb0777e...). Crea 2 verticales raíz y organiza en 2 niveles Categoría›Subcategoría:
--   • Salud y Belleza (raíz) ← anida las 5 subcategorías REALES existentes (con productos).
--   • Tecnología     (raíz) ← subcategorías de referencia Audífonos/Forros (SIN productos por ahora).
--
-- IDEMPOTENTE (WHERE NOT EXISTS + UPDATE condicional) y REVERSIBLE (parent_id self-FK ON DELETE SET NULL:
-- borrar una vertical devuelve sus hijas a raíz; no borra productos). NO cambia products.category_id →
-- los productos siguen colgando de sus hojas beauty; el bot se ve idéntico (una sola vertical con stock →
-- render plano). Tecnología queda invisible al cliente (0 productos vendibles → omitida) hasta stockearse.
--
-- Ejecutar contra prod:  supabase db query --linked -f scripts/seed_kaiu_verticals.sql

DO $$
DECLARE
  v_tid   uuid := '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9';  -- KAIU
  v_salud uuid;
  v_tech  uuid;
BEGIN
  -- 1. Verticales raíz (idempotente).
  INSERT INTO public.product_categories (tenant_id, name, display_label, sort_order, parent_id)
  SELECT v_tid, 'salud_y_belleza', 'Salud y Belleza', 0, NULL
  WHERE NOT EXISTS (SELECT 1 FROM public.product_categories WHERE tenant_id = v_tid AND name = 'salud_y_belleza');

  INSERT INTO public.product_categories (tenant_id, name, display_label, sort_order, parent_id)
  SELECT v_tid, 'tecnologia', 'Tecnología', 1, NULL
  WHERE NOT EXISTS (SELECT 1 FROM public.product_categories WHERE tenant_id = v_tid AND name = 'tecnologia');

  SELECT id INTO v_salud FROM public.product_categories WHERE tenant_id = v_tid AND name = 'salud_y_belleza';
  SELECT id INTO v_tech  FROM public.product_categories WHERE tenant_id = v_tid AND name = 'tecnologia';

  -- 2. Anidar las 5 subcategorías beauty REALES bajo Salud y Belleza (no re-toca si ya anidadas).
  UPDATE public.product_categories
     SET parent_id = v_salud
   WHERE tenant_id = v_tid
     AND name IN ('aceites_vegetales', 'aceites_esenciales', 'jabon', 'kit', 'serum')
     AND parent_id IS DISTINCT FROM v_salud;

  -- 3. Subcategorías de referencia de Tecnología (placeholder, sin productos).
  INSERT INTO public.product_categories (tenant_id, name, display_label, sort_order, parent_id)
  SELECT v_tid, 'audifonos', 'Audífonos', 0, v_tech
  WHERE NOT EXISTS (SELECT 1 FROM public.product_categories WHERE tenant_id = v_tid AND name = 'audifonos');

  INSERT INTO public.product_categories (tenant_id, name, display_label, sort_order, parent_id)
  SELECT v_tid, 'forros', 'Forros', 1, v_tech
  WHERE NOT EXISTS (SELECT 1 FROM public.product_categories WHERE tenant_id = v_tid AND name = 'forros');

  -- Asegura el parent_id de las tech si preexistían planas.
  UPDATE public.product_categories SET parent_id = v_tech
   WHERE tenant_id = v_tid AND name IN ('audifonos', 'forros') AND parent_id IS DISTINCT FROM v_tech;

  RAISE NOTICE 'KAIU verticals: salud=% tech=%', v_salud, v_tech;
END $$;

-- Verificación post-seed (árbol resultante).
SELECT
  COALESCE(p.display_label, '— RAÍZ —') AS vertical,
  c.display_label AS categoria,
  c.name
FROM public.product_categories c
LEFT JOIN public.product_categories p ON p.id = c.parent_id
WHERE c.tenant_id = '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'
ORDER BY COALESCE(p.sort_order, c.sort_order), p.display_label NULLS FIRST, c.sort_order;
