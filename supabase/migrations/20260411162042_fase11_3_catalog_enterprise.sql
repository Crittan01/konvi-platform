-- Migración 11.3: Catálogo Enterprise

-- 1. Tabla de Categorías Maestras (Platform Categories)
CREATE TABLE public.platform_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    parent_id UUID REFERENCES public.platform_categories(id), -- Para subcategorías a futuro
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Habilitar RLS en Categorías
ALTER TABLE public.platform_categories ENABLE ROW LEVEL SECURITY;

-- Lectura pública (todos los tenants pueden ver las categorías)
CREATE POLICY "Platform categories are viewable by all authenticated users"
ON public.platform_categories FOR SELECT
TO authenticated
USING (true);

-- Escritura restringida (solo superadmins de plataforma, por ahora bloqueado, solo accesible vía service_role/psql)
CREATE POLICY "Platform categories are read-only for tenants"
ON public.platform_categories FOR ALL
TO authenticated
USING (false);

-- 2. Poblar Categorías (Seeding Inicial Raíz)
INSERT INTO public.platform_categories (name) VALUES
('Tecnología y Celulares'),
('Hogar, Muebles y Jardín'),
('Electrodomésticos'),
('Moda (Ropa y Calzado)'),
('Deportes y Fitness'),
('Belleza y Cuidado Personal'),
('Herramientas y Construcción'),
('Juegos y Juguetes'),
('Accesorios para Vehículos'),
('Salud y Equipamiento Médico'),
('Alimentos y Bebidas'),
('Oficina, Arte y Papelería'),
('Mascotas'),
('Libros, Revistas y Cómics'),
('Bebés'),
('Agro e Industria')
ON CONFLICT (name) DO NOTHING;

-- 3. Modificaciones a la tabla `products` (El Cascarón)
ALTER TABLE public.products
ADD COLUMN platform_category_id UUID REFERENCES public.platform_categories(id),
ADD COLUMN cover_image_url TEXT;

-- 4. Modificaciones a la tabla `product_variations` (El objeto Transaccional)
ALTER TABLE public.product_variations
ADD COLUMN sku TEXT,
ADD COLUMN compare_at_price DECIMAL(10, 2),
ADD COLUMN weight_kg DECIMAL(6, 3),
ADD COLUMN length_cm DECIMAL(6, 2),
ADD COLUMN width_cm DECIMAL(6, 2),
ADD COLUMN height_cm DECIMAL(6, 2),
ADD COLUMN image_url TEXT;

-- Vamos a generar SKUs pseudo-aleatorios (VAR- + los primeros 8 chars del ID) para la data existente, asegurando compatibilidad
UPDATE public.product_variations
SET sku = 'VAR-' || UPPER(SUBSTRING(id::text FROM 1 FOR 8)) || '-' || UPPER(SUBSTRING(tenant_id::text FROM 1 FOR 4))
WHERE sku IS NULL;

-- Ahora podemos hacer que SKU sea NOT NULL de forma segura
ALTER TABLE public.product_variations ALTER COLUMN sku SET NOT NULL;

-- Un producto bajo un mismo tenant NO puede tener el mismo SKU dos veces
ALTER TABLE public.product_variations ADD CONSTRAINT uc_tenant_sku UNIQUE (tenant_id, sku);
