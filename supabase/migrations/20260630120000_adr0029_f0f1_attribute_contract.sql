-- IDEMPOTENCIA (2026-07-25): las tablas usan CREATE TABLE IF NOT EXISTS pero los
-- CREATE POLICY no tenían guarda, así que re-correr la migración sobre una base
-- donde parte ya existe abortaba con 'policy ... already exists'. Se detectó al
-- intentar aplicarla a prod: `product_attribute_definitions` YA estaba creada por
-- otra vía y su policy también, mientras `category_attributes` y `attribute_values`
-- no existían — o sea, prod quedó a medio camino y la migración no podía completarla.
-- Añadir DROP POLICY IF EXISTS antes de cada CREATE la vuelve re-ejecutable sin
-- cambiar el esquema resultante (mismo patrón que ya usa
-- 20260627120000_product_categories_per_tenant.sql).

-- ADR-0029 F0+F1 — Fundación del modelo de producto multi-vertical: contrato de atributos por categoría.
--
-- ADITIVA · idempotente (IF NOT EXISTS) · nullable · sin NOT NULL sobre datos existentes → NO rompe
-- inserts/queries vivos. NO reemplaza platform_categories/product_categories (ADR-0027): las ENRIQUECE.
-- Aplicar local→remoto con autorización explícita del founder (protocolo de migraciones).
--
-- F0: platform_categories adopta identidad de taxonomía estándar (Shopify GID + mapeo Google) y las
--     categorías operativas del tenant pueden ENLAZARSE a un nodo de taxonomía (para heredar atributos).
-- F1: contrato categoría→atributos-válidos→valores-permitidos (tipado), + extensión per-tenant (D3).

-- ── F0 · taxonomía adoptable ────────────────────────────────────────────────────────────────────
ALTER TABLE public.platform_categories
  ADD COLUMN IF NOT EXISTS gid                TEXT,   -- GID estable Shopify (identidad de negocio, sobrevive renombres)
  ADD COLUMN IF NOT EXISTS full_path          TEXT,   -- 'Health & Beauty > Personal Care > Cosmetics'
  ADD COLUMN IF NOT EXISTS google_category_id TEXT,   -- mapeo a Google Product Taxonomy (feed/marketplace)
  ADD COLUMN IF NOT EXISTS taxonomy_version   TEXT;   -- versión CalVer anclada (bump deliberado)

COMMENT ON COLUMN public.platform_categories.gid IS
  'ADR-0029 D1: identidad estable de la Shopify Standard Product Taxonomy. Es la clave de negocio, no el UUID aleatorio.';

-- La categoría OPERATIVA del tenant (ADR-0027) puede enlazarse a un nodo de taxonomía → hereda su
-- contrato de atributos. Nullable: no obliga a mapear (el tenant puede curar atributos propios).
ALTER TABLE public.product_categories
  ADD COLUMN IF NOT EXISTS platform_category_id UUID REFERENCES public.platform_categories(id) ON DELETE SET NULL;

-- ── F1 · contrato de atributos por categoría (curado, global) ───────────────────────────────────
-- Qué atributos VÁLIDOS tiene cada nodo de taxonomía. Curado por Konvi (D3 híbrido: núcleo curado).
CREATE TABLE IF NOT EXISTS public.category_attributes (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_category_id UUID NOT NULL REFERENCES public.platform_categories(id) ON DELETE CASCADE,
    code                 TEXT NOT NULL,                       -- clave canónica ('volume','concentration')
    label                TEXT NOT NULL,                       -- etiqueta visible ('Volumen')
    type                 TEXT NOT NULL CHECK (type IN ('select','metric','number','boolean','text')),
    unit                 TEXT,                                -- para type='metric' (ml, g)
    is_required          BOOLEAN NOT NULL DEFAULT false,
    is_variant_axis      BOOLEAN NOT NULL DEFAULT false,      -- ¿crea variante (SKU distinto)? (ADR-0029 P3)
    localizable          BOOLEAN NOT NULL DEFAULT false,      -- valores traducibles (patrón Akeneo)
    sort_order           INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (platform_category_id, code)
);
ALTER TABLE public.category_attributes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "category_attributes readable by authenticated" ON public.category_attributes;
CREATE POLICY "category_attributes readable by authenticated"
  ON public.category_attributes FOR SELECT TO authenticated USING (true);

-- Valores permitidos (enum cerrado) de cada atributo. anti-alucinación por SET membership (ADR-0024).
CREATE TABLE IF NOT EXISTS public.attribute_values (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_attribute_id UUID NOT NULL REFERENCES public.category_attributes(id) ON DELETE CASCADE,
    value                 TEXT NOT NULL,                      -- '10ml', '100% puro'
    gid                   TEXT,                               -- TaxonomyValue GID Shopify (si aplica)
    meta                  JSONB NOT NULL DEFAULT '{}',        -- ej. {"hex":"#FF0000"} para swatches
    sort_order            INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category_attribute_id, value)
);
ALTER TABLE public.attribute_values ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "attribute_values readable by authenticated" ON public.attribute_values;
CREATE POLICY "attribute_values readable by authenticated"
  ON public.attribute_values FOR SELECT TO authenticated USING (true);

-- Extensión per-tenant (D3): el tenant agrega atributos propios tipados a SU categoría operativa.
CREATE TABLE IF NOT EXISTS public.product_attribute_definitions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    product_category_id UUID REFERENCES public.product_categories(id) ON DELETE CASCADE,
    code                TEXT NOT NULL,
    label               TEXT NOT NULL,
    type                TEXT NOT NULL CHECK (type IN ('select','metric','number','boolean','text')),
    unit                TEXT,
    is_required         BOOLEAN NOT NULL DEFAULT false,
    is_variant_axis     BOOLEAN NOT NULL DEFAULT false,
    allowed_values      JSONB NOT NULL DEFAULT '[]',          -- enum de valores permitidos (type='select')
    localizable         BOOLEAN NOT NULL DEFAULT false,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, product_category_id, code)
);
ALTER TABLE public.product_attribute_definitions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Tenant Isolation" ON public.product_attribute_definitions;
CREATE POLICY "Tenant Isolation"
  ON public.product_attribute_definitions FOR ALL
  USING (tenant_id = public.app_current_tenant())
  WITH CHECK (tenant_id = public.app_current_tenant());
CREATE INDEX IF NOT EXISTS idx_prod_attr_defs_tenant_cat
  ON public.product_attribute_definitions (tenant_id, product_category_id);
