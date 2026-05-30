-- =============================================================================
-- Rev. 105 (Sem 2, F.9 / MA-7) — compliance_enforcement_log: audit append-only
-- de hits a decoradores compliance. Permite auditoría regulatoria + métricas
-- de gates evitando incidentes (cuántos requests fueron bloqueados, por qué,
-- y a qué endpoint).
--
-- Disparador: meta-análisis cross-dossier 2026-05-05 — compliance cruza los 6
-- providers (Habeas Data Ley 1581 aplica a TODOS los datos personales, Meta
-- Business Policy a WhatsApp, Wompi TOS a payments, Envia TOS a shipping,
-- MeLi CBT a marketplace, etc.). F.9 expande de 1 decorador genérico a 7+
-- decoradores específicos.
--
-- Retention: 7 años por Habeas Data Ley 1581 ART. 17 (auditoría).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.compliance_enforcement_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
        -- Nullable: algunos decoradores aplican fuera de tenant context
        -- (ej. webhooks pre-resolución).
    decorator       TEXT NOT NULL,
        -- snake_case canonical: 'requires_consent' | 'enforce_meta_24h_window' |
        -- 'enforce_csw_template_only_outside_24h' | 'audit_data_access' |
        -- 'scoped_to_country' | 'requires_verified_dkim_spf' |
        -- 'enforce_pci_scope' | 'enforce_meli_cbt_response_sla'
    target_function TEXT NOT NULL,
        -- Nombre fully-qualified de la función decorada (módulo.función).
    outcome         TEXT NOT NULL,
        -- 'allowed' | 'blocked'
    blocked_reason  TEXT,
        -- NULL si outcome=allowed; razón humana si blocked.
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- Contexto opcional: scope, country, contact_id, etc.
    request_id      TEXT,
        -- Correlación con OpenTelemetry trace (futuro F.6).
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT compliance_enforcement_log_outcome_chk
        CHECK (outcome IN ('allowed', 'blocked'))
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Forensics: "todos los hits del decorator X para tenant Y en período".
CREATE INDEX IF NOT EXISTS compliance_enforcement_log_tenant_dec_idx
    ON public.compliance_enforcement_log
    (tenant_id, decorator, evaluated_at DESC)
    WHERE tenant_id IS NOT NULL;

-- "Eventos de bloqueo recientes" (alertas, dashboard).
CREATE INDEX IF NOT EXISTS compliance_enforcement_log_blocked_idx
    ON public.compliance_enforcement_log (decorator, evaluated_at DESC)
    WHERE outcome = 'blocked';

-- Retention queries.
CREATE INDEX IF NOT EXISTS compliance_enforcement_log_evaluated_at_idx
    ON public.compliance_enforcement_log (evaluated_at DESC);

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.compliance_enforcement_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS compliance_enforcement_log_tenant_select
    ON public.compliance_enforcement_log;
CREATE POLICY compliance_enforcement_log_tenant_select
    ON public.compliance_enforcement_log
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT solo via service_role (los decoradores corren con privilegio de
-- servidor; UPDATE/DELETE prohibidos — append-only).

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.compliance_enforcement_log IS
    'Audit append-only de hits a decoradores compliance. Rev. 105 Sem 2 F.9 '
    '(MA-7). Habeas Data Ley 1581 ART. 17 — retención 7 años. Cada call a '
    'función decorada genera 1 row con outcome=allowed|blocked + metadata.';

COMMENT ON COLUMN public.compliance_enforcement_log.decorator IS
    'snake_case canonical. Lista en services/api/lib/compliance/decorators.py.';

COMMENT ON COLUMN public.compliance_enforcement_log.outcome IS
    'allowed = decorator dejó pasar la call. blocked = levantó '
    'ComplianceViolationError; función no se ejecutó.';
