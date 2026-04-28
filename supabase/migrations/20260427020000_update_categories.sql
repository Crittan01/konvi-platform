-- Reemplaza las 16 categorías tech-genéricas por categorías relevantes para SMBs colombianos.
-- Cubre los sectores más comunes: belleza/natural, moda, alimentos, hogar, tech, mascotas.
-- Las categorías old (Tecnología y Celulares, Agro e Industria, etc.) no aplican
-- a la mayoría de tenants del producto (commerce-ops para WhatsApp).

-- Limpiar categorías existentes (no hay FK activos que bloqueen si los productos
-- se actualizan primero, o se pone NULL en products.platform_category_id).
-- Usamos un enfoque safe: DELETE + INSERT con IDs fijos.

DELETE FROM public.platform_categories;

INSERT INTO public.platform_categories (id, name, is_active) VALUES
  (gen_random_uuid(), 'Cuidado Personal y Belleza',  true),
  (gen_random_uuid(), 'Cuidado Facial',               true),
  (gen_random_uuid(), 'Cuidado Corporal',             true),
  (gen_random_uuid(), 'Salud y Bienestar',            true),
  (gen_random_uuid(), 'Aromaterapia y Aceites',       true),
  (gen_random_uuid(), 'Jabones y Productos Naturales',true),
  (gen_random_uuid(), 'Suplementos Naturales',        true),
  (gen_random_uuid(), 'Moda y Accesorios',            true),
  (gen_random_uuid(), 'Ropa Mujer',                   true),
  (gen_random_uuid(), 'Ropa Hombre',                  true),
  (gen_random_uuid(), 'Ropa Niños',                   true),
  (gen_random_uuid(), 'Calzado',                      true),
  (gen_random_uuid(), 'Bisutería y Joyería',          true),
  (gen_random_uuid(), 'Alimentos y Bebidas',          true),
  (gen_random_uuid(), 'Hogar y Decoración',           true),
  (gen_random_uuid(), 'Tecnología',                   true),
  (gen_random_uuid(), 'Mascotas',                     true),
  (gen_random_uuid(), 'Deportes y Fitness',           true),
  (gen_random_uuid(), 'Libros y Papelería',           true),
  (gen_random_uuid(), 'Otros',                        true);

-- Los productos existentes con platform_category_id apuntando a IDs eliminados
-- quedarán con FK roto. Limpiamos esas referencias para evitar errores de join.
UPDATE public.products SET platform_category_id = NULL
WHERE platform_category_id NOT IN (SELECT id FROM public.platform_categories);
