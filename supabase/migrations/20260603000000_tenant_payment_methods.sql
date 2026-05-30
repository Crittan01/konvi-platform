-- =============================================================================
-- Rev. 108 holístico — tenant_payment_methods (modular per-tenant registry).
-- Fecha: 2026-05-27
--
-- Founder feedback 2026-05-27: "Si necesitamos que este sea totalmente
-- modular, no crees?". Diseño simétrico a `tenant_carriers`: cada tenant
-- declara qué métodos de pago acepta. Por defecto todos enabled; el
-- tenant deshabilita en Settings → Pagos lo que NO quiere ofrecer.
--
-- Métodos seedados (rev. 108):
--   • 'cod'           — Contraentrega vía Aveonline (recaudo + liquidación)
--   • 'online_wompi'  — Pago anticipado vía link Wompi (tarjeta/PSE/Nequi)
--
-- Métodos futuros (NO seedados — added when feature shipped):
--   • 'transfer_manual'   — Transferencia bancaria con comprobante manual
--   • 'nequi_direct'      — Link directo Nequi sin Wompi intermediario
--   • 'mercadolibre_link' — Link de pago MeLi para canal cross-platform
--
-- Diseño modular:
--   • CHECK constraint con whitelist explícita — agregar método nuevo
--     requiere migration que extienda whitelist (audit trail visible).
--   • `config_json` per-method para extensiones específicas (ej. COD
--     puede tener `{idasumecosto: 1}`, Wompi `{environment: 'sandbox'}`).
--   • Symmetric con `tenant_carriers` para coherencia del modelo.
--
-- Lookup efectivo:
--   • Sin filas → fallback open (todos enabled) — backward compat.
--   • Con filas → solo `enabled=true` participa.
--
-- Consumidores:
--   • lib/tenant_payment_methods.py — servicio cache TTL 5min.
--   • lib/carrier_capabilities.py — short-circuit cod si NO enabled.
--   • payment_method_explicit invariant — adapta pregunta a métodos
--     disponibles.
--   • payment_method_availability_resolver (pre-LLM) — short-circuit
--     si cliente menciona método no disponible.
--   • prompt builder — bloque [MÉTODOS DE PAGO HABILITADOS].
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.tenant_payment_methods (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    method          TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    display_label   TEXT,
        -- Opcional: nombre amigable mostrado al cliente
        -- (ej. tenant puede preferir "Pago contra recibido" en vez
        -- de "Contraentrega"). Si NULL → label canónico del método.
    config_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Configuración específica del método:
        --   cod          → {min_total_cop?: int, max_total_cop?: int}
        --   online_wompi → {environment?: 'sandbox'|'production'}
        --   futuros      → estructuras propias
    notes           TEXT,
        -- Anotaciones humanas: razón de deshabilitar, link a contrato,
        -- política comercial, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tenant_payment_methods_uniq
        UNIQUE (tenant_id, method),

    -- Whitelist de métodos conocidos. Agregar uno nuevo requiere
    -- migration que extienda este check (audit trail visible).
    CONSTRAINT tenant_payment_methods_valid_method
        CHECK (method IN ('cod', 'online_wompi'))
);

COMMENT ON TABLE public.tenant_payment_methods IS
    'Métodos de pago habilitados per-tenant. Diseño modular simétrico a
     tenant_carriers. Whitelist constrained — extensión via migration.
     Lookup default-open: sin filas → todos enabled (backward compat).';

-- ─── Trigger updated_at ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.tg_tenant_payment_methods_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenant_payment_methods_updated_at
    ON public.tenant_payment_methods;
CREATE TRIGGER tenant_payment_methods_updated_at
    BEFORE UPDATE ON public.tenant_payment_methods
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_tenant_payment_methods_updated_at();

-- ─── Índices ────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS tenant_payment_methods_lookup_idx
    ON public.tenant_payment_methods(tenant_id, method, enabled);

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.tenant_payment_methods ENABLE ROW LEVEL SECURITY;

-- Read: cualquier rol autenticado del tenant.
DROP POLICY IF EXISTS "tenant_payment_methods_read_own"
    ON public.tenant_payment_methods;
CREATE POLICY "tenant_payment_methods_read_own"
    ON public.tenant_payment_methods
    FOR SELECT
    USING (
        auth.role() = 'service_role'
        OR tenant_id = ((current_setting('request.jwt.claims', true)::jsonb -> 'app_metadata' ->> 'tenant_id'))::uuid
    );

-- Write: solo service_role (Settings UI usa endpoint API → service_role).
DROP POLICY IF EXISTS "tenant_payment_methods_write_service"
    ON public.tenant_payment_methods;
CREATE POLICY "tenant_payment_methods_write_service"
    ON public.tenant_payment_methods
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ─── Seed inicial: todos los tenants existentes con ambos métodos enabled ──
-- Backward compat: tenants sin filas → fallback open en la app.
-- Seed explícito permite Settings UI mostrar el estado real desde T=0.

INSERT INTO public.tenant_payment_methods (tenant_id, method, enabled)
SELECT t.id, 'cod', true
FROM public.tenants t
WHERE NOT EXISTS (
    SELECT 1 FROM public.tenant_payment_methods tpm
    WHERE tpm.tenant_id = t.id AND tpm.method = 'cod'
);

INSERT INTO public.tenant_payment_methods (tenant_id, method, enabled)
SELECT t.id, 'online_wompi', true
FROM public.tenants t
WHERE NOT EXISTS (
    SELECT 1 FROM public.tenant_payment_methods tpm
    WHERE tpm.tenant_id = t.id AND tpm.method = 'online_wompi'
);

-- Force PostgREST schema cache reload.
NOTIFY pgrst, 'reload schema';
