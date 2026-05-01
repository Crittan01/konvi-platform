-- Rev. 99 — Click-wrap acceptance del DPA + Privacy Policy.
--
-- Cada tenant debe aceptar explícitamente:
--   • DPA (Data Processing Agreement) — define rol Encargado.
--   • Privacy Policy template — documento que el tenant publica al titular.
--
-- Se versiona el documento (e.g., 'dpa@v2026-05', 'privacy@v2026-05') de
-- modo que un cambio material requiera nueva aceptación.
--
-- Auditable: la fila es append-only (no UPDATE / DELETE).

CREATE TABLE IF NOT EXISTS public.tenant_legal_acceptance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    document_id     TEXT NOT NULL,    -- 'dpa' | 'privacy_policy' | 'subprocessors'
    document_version TEXT NOT NULL,   -- e.g., 'v2026-05-01'
    accepted_by_user_id UUID,         -- auth.users.id
    accepted_by_email TEXT,
    ip_address      INET,
    user_agent      TEXT,
    accepted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_legal_acceptance_tenant
    ON public.tenant_legal_acceptance (tenant_id, document_id, accepted_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_legal_acceptance_version
    ON public.tenant_legal_acceptance (tenant_id, document_id, document_version);

-- ── Append-only via trigger ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fn_block_legal_acceptance_modify()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'tenant_legal_acceptance es append-only (TG_OP=%)', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_block_legal_acceptance_update ON public.tenant_legal_acceptance;
CREATE TRIGGER trg_block_legal_acceptance_update
    BEFORE UPDATE ON public.tenant_legal_acceptance
    FOR EACH ROW EXECUTE FUNCTION public.fn_block_legal_acceptance_modify();

DROP TRIGGER IF EXISTS trg_block_legal_acceptance_delete ON public.tenant_legal_acceptance;
CREATE TRIGGER trg_block_legal_acceptance_delete
    BEFORE DELETE ON public.tenant_legal_acceptance
    FOR EACH ROW EXECUTE FUNCTION public.fn_block_legal_acceptance_modify();

-- ── RLS ─────────────────────────────────────────────────────────────────────
ALTER TABLE public.tenant_legal_acceptance ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legal_acceptance_tenant_select ON public.tenant_legal_acceptance;
CREATE POLICY legal_acceptance_tenant_select ON public.tenant_legal_acceptance
    FOR SELECT TO authenticated
    USING (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS legal_acceptance_tenant_insert ON public.tenant_legal_acceptance;
CREATE POLICY legal_acceptance_tenant_insert ON public.tenant_legal_acceptance
    FOR INSERT TO authenticated
    WITH CHECK (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
              AND tu.role IN ('owner', 'manager')
        )
    );

GRANT SELECT, INSERT ON public.tenant_legal_acceptance TO service_role;
GRANT SELECT, INSERT ON public.tenant_legal_acceptance TO authenticated;

COMMENT ON TABLE public.tenant_legal_acceptance IS
    'Rev. 99 — Click-wrap de DPA / Privacy Policy / Subprocessors. Append-only.';
