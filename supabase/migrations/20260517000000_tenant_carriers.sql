-- =============================================================================
-- Tenant carriers preferences — Sem 5 H.2.7 (rev. 105)
-- Fecha: 2026-05-07
--
-- Permite a cada tenant seleccionar qué carriers (de los disponibles
-- en su provider) quiere ofrecer en cotización. Sin esta tabla, todos
-- los tenants reciben TODOS los carriers que Envia (u otro provider)
-- exponga vía Queries API — incluyendo aquellos que el tenant NO quiere
-- usar (ej. KAIU usa Servientrega + Coordinadora, NO FedEx/DHL).
--
-- Diseño:
--   • Genérica per provider (envia / futuro otros) — provider como key.
--   • Default closed: si NO hay filas para tenant+provider, fallback a
--     "todos enabled" (backward compat con tenants existentes pre-rev105).
--   • Si HAY al menos 1 fila → solo carriers con enabled=true se ofrecen.
--   • capabilities per-carrier opt-in granular (supports_cod, etc.) para
--     futuros H.2.4 (COD) + H.2.5 (insurance) sin re-migration.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_carriers (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
        -- 'envia' | (futuro: otros aggregators si aparecen)
    carrier_code    TEXT NOT NULL,
        -- Snake_case canónico que matchea Envia API (ej. 'servientrega',
        -- 'coordinadora', 'interRapidisimo', 'fedex', 'dhl', 'envia',
        -- 'mensajerosUrbanos', 'tcc', 'deprisa', 'noventa9Minutos').
        -- IMPORTANTE: case-insensitive comparison en aplicación —
        -- Envia API mezcla camelCase con snake_case.
    enabled         BOOLEAN NOT NULL DEFAULT true,
    display_label   TEXT,
        -- Opcional: nombre amigable mostrado en cotización (ej. tenant
        -- puede preferir "Servientrega Express" en vez de código técnico).
        -- Si NULL → usar carrier_code formateado.
    priority        INTEGER NOT NULL DEFAULT 100,
        -- Orden de visualización (menor = primero). Default 100 = sin
        -- preferencia explícita.
    supports_cod    BOOLEAN NOT NULL DEFAULT false,
        -- Capability per-carrier per-tenant: cash on delivery (futuro
        -- H.2.4). Tenant marca cuáles carriers acepta cobrar al
        -- destinatario.
    supports_insurance BOOLEAN NOT NULL DEFAULT false,
        -- Capability per-carrier per-tenant: declaredValue (futuro
        -- H.2.5). Coordinadora EXIGE este flag, otros lo permiten
        -- opcional.
    notes           TEXT,
        -- Anotaciones humanas: razón de deshabilitar, link a contrato,
        -- ETA típico que el tenant prometió a sus clientes, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tenant_carriers_uniq
        UNIQUE (tenant_id, provider, carrier_code)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Lookup principal: cotización filtra por (tenant_id, provider, enabled).
CREATE INDEX IF NOT EXISTS tenant_carriers_lookup_idx
    ON public.tenant_carriers (tenant_id, provider, enabled);

-- Orden visualización en quote.
CREATE INDEX IF NOT EXISTS tenant_carriers_priority_idx
    ON public.tenant_carriers (tenant_id, provider, priority);

-- ─── Trigger updated_at ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tenant_carriers_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenant_carriers_updated_at_trg
    ON public.tenant_carriers;
CREATE TRIGGER tenant_carriers_updated_at_trg
    BEFORE UPDATE ON public.tenant_carriers
    FOR EACH ROW
    EXECUTE FUNCTION public.tenant_carriers_set_updated_at();

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.tenant_carriers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_carriers_isolation ON public.tenant_carriers;
CREATE POLICY tenant_carriers_isolation
    ON public.tenant_carriers
    FOR ALL
    USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.tenant_carriers IS
    'Sem 5 H.2.7. Preferencias de carriers por tenant per provider. '
    'Filtra resultados de quote — solo carriers enabled aparecen al '
    'cliente. Default open: tenant sin filas → todos los carriers '
    'globales de Envia. Tenant con ≥1 fila → solo enabled=true.';

COMMENT ON COLUMN public.tenant_carriers.carrier_code IS
    'Identificador del carrier según Envia API. Case-insensitive en '
    'application layer (Envia mezcla camelCase y snake_case).';

COMMENT ON COLUMN public.tenant_carriers.supports_cod IS
    'Cash on delivery per-carrier (futuro H.2.4). Tenant marca cuáles '
    'carriers acepta cobrar al destinatario.';

COMMENT ON COLUMN public.tenant_carriers.supports_insurance IS
    'Declared value per-carrier (futuro H.2.5). Coordinadora exige '
    'este flag siempre.';
