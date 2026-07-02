-- F2 (roadmap producción) — DATA seed: contratos de atributos tipados por categoría para KAIU.
--
-- Aterriza ADR-0029 D3/D4: cada subcategoría lleva su contrato (product_attribute_definitions) que
-- (a) guía el alta hacia valores canónicos y (b) el server valida HARD (products.py) → el bot cita
-- atributos como HECHOS gobernados (anti-alucinación, SET membership ADR-0024). Enums COMPLETADOS desde
-- docs/research/vertical-templates-proposal-2026-07-01.md (datos de prueba, se afinan luego con el founder).
--
-- Grounding: Shopify Std Product Taxonomy + MercadoLibre CO + schema.org. is_variant_axis=TRUE → eje de SKU.
-- IDEMPOTENTE (ON CONFLICT por (tenant_id, product_category_id, code) → re-ejecutable, actualiza). Resuelve
-- product_category_id por NAME (no hardcodea uuids). NO toca productos. allowed_values sin unidad (la UI la anexa).
--
-- Ejecutar:  supabase db query --linked -f scripts/seed_kaiu_attribute_contracts.sql

DO $$
DECLARE v_tid uuid := '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9';  -- KAIU
BEGIN
  -- Reconciliación: elimina definiciones STALE de un seed previo (codes en inglés volume/weight/
  -- active_ingredient) que colisionan por LABEL con las de abajo → evita 2 "Volumen"/"Peso" por categoría.
  -- 'contents' (kit) NO colisiona y se conserva.
  DELETE FROM public.product_attribute_definitions
  WHERE tenant_id = v_tid AND code IN ('volume', 'weight', 'active_ingredient');

  INSERT INTO public.product_attribute_definitions
    (tenant_id, product_category_id, code, label, type, unit, is_variant_axis, allowed_values, sort_order)
  SELECT v_tid, c.id, x.code, x.label, x.type, x.unit, x.variant, x.allowed::jsonb, x.sort
  FROM (VALUES
    -- ── Salud y Belleza ──────────────────────────────────────────────────────────────────────
    -- Aceites Esenciales
    ('aceites_esenciales','volumen','Volumen','metric','ml',  TRUE,  '[5,10,15,30,50]', 0),
    ('aceites_esenciales','aroma','Aroma','select',NULL,      FALSE, '["Lavanda","Eucalipto","Menta","Romero","Árbol de té","Naranja","Limón","Toronja","Canela","Hierbabuena"]', 1),
    ('aceites_esenciales','puro','100% puro','boolean',NULL,  FALSE, '[]', 2),
    ('aceites_esenciales','uso_recomendado','Uso recomendado','select',NULL, FALSE, '["Aromaterapia / difusor","Uso tópico (diluido)","Masaje"]', 3),
    -- Aceites Vegetales / Portadores
    ('aceites_vegetales','volumen','Volumen','metric','ml',   TRUE,  '[30,60,120]', 0),
    ('aceites_vegetales','aceite_base','Aceite base','select',NULL,  FALSE, '["Almendras dulces","Argán","Coco","Jojoba","Rosa mosqueta","Semilla de uva","Aguacate","Ricino","Oliva","Otro"]', 1),
    ('aceites_vegetales','extraccion','Extracción','select',NULL,    FALSE, '["Prensado en frío","Refinado","Sin refinar"]', 2),
    ('aceites_vegetales','tipo_piel','Tipo de piel','select',NULL,   FALSE, '["Todo tipo","Seca","Grasa","Mixta","Sensible"]', 3),
    -- Sérums Faciales
    ('serum','volumen','Volumen','metric','ml',               TRUE,  '[15,30,50]', 0),
    ('serum','ingrediente_activo','Ingrediente activo','select',NULL, FALSE, '["Ácido hialurónico","Vitamina C","Niacinamida","Retinol","Bakuchiol","Ácido salicílico"]', 1),
    ('serum','tipo_piel','Tipo de piel','select',NULL,        FALSE, '["Todo tipo","Seca","Grasa","Mixta","Sensible"]', 2),
    -- Jabones Artesanales
    ('jabon','aroma','Aroma','select',NULL,                   TRUE,  '["Lavanda","Eucalipto","Menta","Coco","Avena y Miel","Rosa Mosqueta","Caléndula","Aloe Vera","Carbón Activado","Café","Cítricos","Sin Fragancia"]', 0),
    ('jabon','peso','Peso','metric','g',                      FALSE, '[60,100,150]', 1),
    ('jabon','tipo_piel','Tipo de piel','select',NULL,        FALSE, '["Piel seca","Piel grasa","Piel normal","Piel mixta","Piel sensible","Todo tipo"]', 2),
    ('jabon','ingrediente_principal','Ingrediente principal','text',NULL, FALSE, '[]', 3),
    -- ── Tecnología ───────────────────────────────────────────────────────────────────────────
    -- Audífonos
    ('audifonos','color','Color','select',NULL,               TRUE,  '["Negro","Blanco","Azul","Rosado","Verde","Rojo","Gris"]', 0),
    ('audifonos','tipo_audifono','Tipo de audífono','select',NULL, FALSE, '["In-ear","On-ear","Over-ear","Neckband","Clip-ear","Open-ear"]', 1),
    ('audifonos','conectividad','Conectividad','select',NULL, FALSE, '["Inalámbrico Bluetooth","Cable"]', 2),
    ('audifonos','cancelacion_ruido','Cancelación de ruido','boolean',NULL, FALSE, '[]', 3),
    ('audifonos','autonomia_bateria','Autonomía de batería','metric','h', FALSE, '[]', 4),
    -- Forros / Estuches para Audífonos
    ('forros','modelo_compatible','Modelo compatible','select',NULL, TRUE, '["AirPods Pro 2","AirPods Pro (1ª gen)","AirPods 3","AirPods 2/1","AirPods 4","Samsung Galaxy Buds","JBL","Motorola Buds","Xiaomi/Redmi Buds","Universal/genérico"]', 0),
    ('forros','color','Color','select',NULL,                  TRUE,  '["Negro","Blanco","Transparente","Rosado","Azul","Verde","Rojo","Morado","Gris"]', 1),
    ('forros','material','Material','select',NULL,            FALSE, '["Silicona","TPU","Cuero sintético","Plástico rígido","Neopreno/tela"]', 2),
    ('forros','con_mosqueton','Con mosquetón / llavero','boolean',NULL, FALSE, '[]', 3)
  ) AS x(cat_name, code, label, type, unit, variant, allowed, sort)
  JOIN public.product_categories c ON c.tenant_id = v_tid AND c.name = x.cat_name
  ON CONFLICT (tenant_id, product_category_id, code) DO UPDATE
    SET label = EXCLUDED.label, type = EXCLUDED.type, unit = EXCLUDED.unit,
        is_variant_axis = EXCLUDED.is_variant_axis, allowed_values = EXCLUDED.allowed_values,
        sort_order = EXCLUDED.sort_order;
END $$;

-- Verificación: contrato por categoría.
SELECT c.display_label AS categoria, d.label AS atributo, d.type,
       d.is_variant_axis AS variante, jsonb_array_length(d.allowed_values) AS n_valores
FROM public.product_attribute_definitions d
JOIN public.product_categories c ON c.id = d.product_category_id
WHERE d.tenant_id = '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'
ORDER BY c.display_label, d.sort_order;
