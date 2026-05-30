-- =============================================================================
-- Sem 7 F2 cierre 2026-05-20 — Multi-tenant pitch + product groups.
--
-- Bug P1 founder UAT (conv 7053666a): el prompt del bot decía hardcoded
-- "Trabajamos cosmética artesanal 100% natural" + lista 4 categorías de
-- KAIU. Para un tenant de tech/relojes/accesorios eso es inaceptable.
--
-- Solución: 3 columnas opcionales en `tenants` que dejan al tenant
-- configurar cómo el bot se presenta y qué grupos de producto muestra.
--
-- Acuerdo founder 2026-05-20 (P1 reformulado): NO usar "categorías"
-- formales (ambiguas, ej. sérum vs "salud y bienestar"). Usar lenguaje
-- natural del tenant.
-- =============================================================================

-- business_pitch: descripción 1-frase del negocio que el bot menciona al
-- saludar a un cliente nuevo.
--   - KAIU: "Cosmética artesanal 100% natural"
--   - Tech tenant: "Accesorios para celulares y tecnología móvil"
--   - Relojería: "Relojería de autor y accesorios"
-- Si NULL/vacío → el bot omite la frase de pitch (saludo simple).
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS business_pitch TEXT;

COMMENT ON COLUMN public.tenants.business_pitch IS
    'Sem 7 F2 cierre 2026-05-20 — frase corta (≤120 chars) que el bot '
    'menciona al saludar cliente nuevo. Ej KAIU: "Cosmética artesanal '
    '100% natural". Si NULL, el bot omite la frase.';

-- product_groups: array opcional de strings con las "líneas de producto"
-- que el bot menciona cuando el cliente pregunta "qué venden". Si vacío,
-- el bot deriva del catálogo (primer token significativo de cada title).
--   - KAIU: ["Aceites vegetales", "Aceites esenciales", "Jabones artesanales", "Sérums faciales"]
--   - Tech: ["Carcasas", "Cables", "Audífonos", "Cargadores"]
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS product_groups JSONB
    NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.tenants.product_groups IS
    'Sem 7 F2 cierre 2026-05-20 — array de strings con las líneas de '
    'producto que el bot presenta. Si vacío, deriva del catálogo. '
    'NO son "categorías" formales — usa lenguaje natural del tenant.';

-- show_prices_in_catalog: si true (default), el bot muestra precios en
-- los listados de productos. Si false, solo muestra el producto y pide
-- consulta personalizada (modelo B2B custom / luxury).
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS show_prices_in_catalog BOOLEAN
    NOT NULL DEFAULT true;

COMMENT ON COLUMN public.tenants.show_prices_in_catalog IS
    'Sem 7 F2 cierre 2026-05-20 — si true, bot incluye precios en '
    'listados de catálogo. false para tenants premium/B2B custom.';
