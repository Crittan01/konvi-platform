-- =============================================================================
-- Rev. 108 — Canonical carrier capabilities matrix per Aveonline carrier.
-- Fecha: 2026-05-26
--
-- Contexto: el founder pidió un MODELO UNIFICADO de capacidades por carrier
-- (no parches per-tenant). Datos curados desde `docs/research/aveonline-
-- dossier.md` §3.10.2 (limits) + §7.2 (COD + liquidación + devolución)
-- + §7.3 (comisiones). Refresh trimestral per `docs/research/changelog-
-- watch.md`.
--
-- Propósito (holístico):
--   1. **Single source of truth** platform-level (NO per-tenant). Todos
--      los tenants heredan estos defaults — overrideables vía
--      `tenant_carriers.cod_override` para acuerdos especiales.
--   2. **Bot prompt context** — el prompt builder lee esta tabla cada
--      turno para informar al LLM con capacidades reales por carrier.
--   3. **Hard-filter pre-quote** — `shipping_quote_tool` filtra carriers
--      incompatibles ANTES de mostrar al cliente (sin mínimo, peso máx,
--      etc.) → 0 falsos procesos donde cliente da PII y al final guía
--      falla.
--   4. **UI tenant assertive** — Settings → Aveonline → Carriers muestra
--      a tenant todas las capacidades de cada carrier (mín recaudo, días
--      liquidación, ⚠️cobra-devolución, comisión COD).
--   5. **Mensaje cliente informado** — resumen pre-pago muestra warning
--      condicional si `charges_return_fee=true` para que cliente sepa
--      "a qué se atiene" en caso de rechazo.
--
-- Diseño:
--   • `carrier_id` puede ser NULL para carriers con ID asignado por
--     cuenta (DOMINA, SAFERBO, MOOVA, 99MINUTOS, GO ENVIOS — dossier
--     §3.5 line 288). Lookup primario por `carrier_name` UPPERCASE.
--   • Campos COD nullables si dato no documentado — operador puede
--     completar via Settings UI o asesor logístico Aveonline.
--   • `last_verified_date` + `fuente_doc_url` para auditabilidad.
--   • RLS read-only para todos los tenants autenticados (tabla
--     platform-level — datos públicos).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.aveonline_carrier_capabilities (
    carrier_name        TEXT PRIMARY KEY,
        -- UPPERCASE canónico: 'SERVIENTREGA' | 'ENVIA' | 'COORDINADORA'
        -- | 'TCC' | 'INTERRAPIDISIMO' | 'DOMINA' | 'SAFERBO' | 'MOOVA'
        -- | '99MINUTOS' | 'GO ENVIOS' | 'DEPRISA'.
    carrier_id          TEXT,
        -- ID Aveonline cuando es estable (29, 33, 1009, 1010, 1016).
        -- NULL para carriers con ID asignado por cuenta — el client
        -- runtime descubre vía `listarTransportadorasPorEmpresa` y
        -- matchea por carrier_name.

    -- ─── COD capability ────────────────────────────────────────────────
    supports_cod                BOOLEAN NOT NULL DEFAULT false,
    cod_min_recaudo_cop         INTEGER,
        -- Mínimo de recaudo COD bajo este carrier. NULL = sin mínimo
        -- documentado (no significa "no aplica" — significa "research gap").
    cod_min_recaudo_heavy_cop   INTEGER,
        -- Mínimo de recaudo cuando peso > `cod_weight_threshold_kg`
        -- (Interrapidisimo: $45k ≤2kg / $60k 2.1-5kg).
    cod_weight_threshold_kg     NUMERIC,
    cod_commission_pct          NUMERIC,
        -- % comisión Aveonline sobre monto recaudado. Default 2.40%
        -- per dossier §7.3 — algunos carriers pueden tener tarifa distinta.
    cod_liquidation_days_range  TEXT,
        -- "4-6" | "7-11" | "5-11" — días hábiles para liquidación
        -- después de entrega.
    cod_liquidation_weekday     TEXT,
        -- "viernes" | "martes y viernes" — día de pago del recaudo
        -- al tenant.

    -- ─── Returns (CRÍTICO: cobra al tenant si cliente rechaza) ────────
    charges_return_fee  BOOLEAN NOT NULL DEFAULT false,
        -- TRUE = carrier cobra costo de devolución al tenant si cliente
        -- rechaza paquete. ENVIA + COORDINADORA = TRUE (dossier §7.2).
        -- Bot muestra warning condicional al cliente.

    -- ─── Package constraints (peso/dim/valor) ─────────────────────────
    max_weight_kg               NUMERIC,
    max_dim_cm                  INTEGER,
        -- Arista máxima en cm.
    factor_volumetrico          INTEGER,
        -- Divisor para peso volumétrico (g/cm³). Coordinadora: 2500.
        -- Interrapidisimo: 6000.
    valor_declarado_min_cop     INTEGER NOT NULL DEFAULT 10000,
        -- Mínimo común Aveonline (numbererror -5, dossier §14.2 line 941).
    valor_declarado_max_cop     INTEGER,

    -- ─── Provenance + audit ────────────────────────────────────────────
    fuente_doc_url      TEXT,
    last_verified_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.aveonline_carrier_capabilities IS
    'Canonical carrier capability matrix para provider Aveonline.
     Datos curados desde docs/research/aveonline-dossier.md.
     Refresh trimestral per changelog-watch.md. Platform-level (NOT
     per-tenant): tenants heredan defaults, overrideables vía
     tenant_carriers.cod_override.';

-- ─── Trigger updated_at ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tg_aveonline_carrier_capabilities_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS aveonline_carrier_capabilities_updated_at
    ON public.aveonline_carrier_capabilities;
CREATE TRIGGER aveonline_carrier_capabilities_updated_at
    BEFORE UPDATE ON public.aveonline_carrier_capabilities
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_aveonline_carrier_capabilities_updated_at();

-- ─── RLS (read-only para todos los autenticados) ──────────────────────────

ALTER TABLE public.aveonline_carrier_capabilities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "aveonline_carrier_capabilities_read_all"
    ON public.aveonline_carrier_capabilities;
CREATE POLICY "aveonline_carrier_capabilities_read_all"
    ON public.aveonline_carrier_capabilities
    FOR SELECT
    USING (auth.role() = 'authenticated' OR auth.role() = 'service_role');

-- Write solo service_role (seed + refresh trimestral).
DROP POLICY IF EXISTS "aveonline_carrier_capabilities_write_service"
    ON public.aveonline_carrier_capabilities;
CREATE POLICY "aveonline_carrier_capabilities_write_service"
    ON public.aveonline_carrier_capabilities
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ─── Seed inicial (10 carriers documentados en dossier) ───────────────────
-- Fuente: docs/research/aveonline-dossier.md secciones §3.10.2 + §7.2 + §7.3.
-- Last verified: 2026-05-21 (dossier verification date).

INSERT INTO public.aveonline_carrier_capabilities (
    carrier_name, carrier_id, supports_cod,
    cod_min_recaudo_cop, cod_min_recaudo_heavy_cop, cod_weight_threshold_kg,
    cod_commission_pct, cod_liquidation_days_range, cod_liquidation_weekday,
    charges_return_fee,
    max_weight_kg, max_dim_cm, factor_volumetrico,
    valor_declarado_min_cop, valor_declarado_max_cop,
    fuente_doc_url, notes
) VALUES
    -- SERVIENTREGA: mercancías mín $25k, sin costo devolución, 7-11d viernes
    ('SERVIENTREGA', '33', true,
     25000, NULL, NULL,
     2.40, '7-11', 'viernes',
     false,
     3, NULL, NULL,
     10000, NULL,
     'https://encolombia.com/economia/empresas/comerciop/servientrega-precios-tarifas',
     'Mercancías: peso ≥3kg, mín recaudo $25k. Documentos: 2kg, mín $5k. Sin costo devolución.'),

    -- ENVIA: SÍ cobra devolución (CRÍTICO), liquidación 7-11d (contrato 9-15)
    ('ENVIA', '29', true,
     NULL, NULL, NULL,
     2.40, '7-11', 'viernes',
     true,
     8, NULL, NULL,
     10000, NULL,
     'https://envia.co/servicios',
     'Cobra costo devolución si cliente rechaza (dossier §7.2). Mín recaudo no documentado — consultar asesor.'),

    -- COORDINADORA: SÍ cobra devolución, factor volumétrico 2500
    ('COORDINADORA', '1009', true,
     NULL, NULL, NULL,
     2.40, '5-11', NULL,
     true,
     5, 50, 2500,
     10000, 200000,
     'https://coordinadora.com/envios/tarifas-e-informacion-general/',
     'Cobra costo devolución si cliente rechaza. Exige valorDeclarado siempre. Aristas máx 50cm.'),

    -- TCC: 4-6d hábiles martes+viernes, sin devolución, máx $3.5M
    ('TCC', '1010', true,
     NULL, NULL, NULL,
     2.40, '4-6', 'martes y viernes',
     false,
     5, NULL, NULL,
     10000, 3511000,
     'https://tcc.com.co/courier/mensajeria/formas-de-pago-y-tarifas/',
     'Liquidación más rápida (martes+viernes). Valor máx $3.511.000.'),

    -- INTERRAPIDISIMO: mín $45k (≤2kg) / $60k (2.1-5kg), factor 6000
    ('INTERRAPIDISIMO', '1016', true,
     45000, 60000, 2.0,
     2.40, '7-11', 'viernes',
     false,
     5, NULL, 6000,
     10000, NULL,
     'https://interrapidisimo.com/wp-content/uploads/2025/01/CONSOLIDADO-DE-TARIFAS-2025-2026.pdf',
     'Mín recaudo varía por peso: ≤2kg=$45k, 2.1-5kg=$60k. Factor volumétrico 6000.'),

    -- DOMINA: 4-6d martes+viernes, sin devolución
    ('DOMINA', NULL, true,
     NULL, NULL, NULL,
     2.40, '4-6', 'martes y viernes',
     false,
     NULL, NULL, NULL,
     10000, NULL,
     'https://aveonline.co/servicios-pago-contraentrega/',
     'ID asignado por cuenta (dossier §3.5). Liquidación rápida. Mín recaudo no documentado.'),

    -- SAFERBO: 7-11d viernes, sin devolución, mensajería 1kg
    ('SAFERBO', NULL, true,
     NULL, NULL, NULL,
     2.40, '7-11', 'viernes',
     false,
     1, NULL, NULL,
     10000, NULL,
     'https://thesaferbo.com/',
     'ID asignado por cuenta. Mensajería 1kg, carga express 5-30kg (aristas 1.5m).'),

    -- MOOVA: liquidación no documentada, sin devolución
    ('MOOVA', NULL, true,
     NULL, NULL, NULL,
     2.40, NULL, NULL,
     false,
     NULL, NULL, NULL,
     10000, NULL,
     NULL,
     'ID asignado por cuenta. Liquidación COD no documentada — consultar asesor antes de habilitar producción.'),

    -- 99MINUTOS: NO soporta COD (no aparece en dossier §7.2)
    ('99MINUTOS', NULL, false,
     NULL, NULL, NULL,
     NULL, NULL, NULL,
     false,
     NULL, NULL, NULL,
     10000, NULL,
     NULL,
     'NO soporta contraentrega (no documentado en dossier §7.2). Solo pago anticipado.'),

    -- GO ENVIOS: NO soporta COD
    ('GO ENVIOS', NULL, false,
     NULL, NULL, NULL,
     NULL, NULL, NULL,
     false,
     NULL, NULL, NULL,
     10000, NULL,
     NULL,
     'NO soporta contraentrega (no documentado en dossier §7.2). Solo pago anticipado.')

ON CONFLICT (carrier_name) DO UPDATE SET
    carrier_id                  = EXCLUDED.carrier_id,
    supports_cod                = EXCLUDED.supports_cod,
    cod_min_recaudo_cop         = EXCLUDED.cod_min_recaudo_cop,
    cod_min_recaudo_heavy_cop   = EXCLUDED.cod_min_recaudo_heavy_cop,
    cod_weight_threshold_kg     = EXCLUDED.cod_weight_threshold_kg,
    cod_commission_pct          = EXCLUDED.cod_commission_pct,
    cod_liquidation_days_range  = EXCLUDED.cod_liquidation_days_range,
    cod_liquidation_weekday     = EXCLUDED.cod_liquidation_weekday,
    charges_return_fee          = EXCLUDED.charges_return_fee,
    max_weight_kg               = EXCLUDED.max_weight_kg,
    max_dim_cm                  = EXCLUDED.max_dim_cm,
    factor_volumetrico          = EXCLUDED.factor_volumetrico,
    valor_declarado_min_cop     = EXCLUDED.valor_declarado_min_cop,
    valor_declarado_max_cop     = EXCLUDED.valor_declarado_max_cop,
    fuente_doc_url              = EXCLUDED.fuente_doc_url,
    last_verified_date          = EXCLUDED.last_verified_date,
    notes                       = EXCLUDED.notes;

-- Force PostgREST schema cache reload.
NOTIFY pgrst, 'reload schema';
