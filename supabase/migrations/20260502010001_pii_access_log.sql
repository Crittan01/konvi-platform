-- =============================================================================
-- Rev. 93 — Habeas Data Art. 9: log de accesos a PII (auditoría interna).
--
-- Cada vez que un user (operador) o un agent (bot, integración) lee
-- los campos PII de un contact, se inserta un row aquí. Permite al
-- tenant demostrar a SIC quién accedió a qué dato y cuándo, en
-- caso de auditoría o queja del titular.
--
-- NO se loguea cada SELECT — solo cuando el access es explícito (vía
-- helper `pii_access(...)`). Esto evita inflación del log con queries
-- sistémicas (rendering UI, sync background, etc.).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.pii_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    contact_id      UUID NOT NULL,
    accessed_by     TEXT NOT NULL,         -- 'user:<email>' | 'agent:orchestrator' | 'integration:wompi'
    actor_user_id   UUID,                  -- si fue user del tenant
    purpose         TEXT NOT NULL,         -- 'wompi_checkout' | 'inbox_view' | 'data_export' | 'order_create' | 'support'
    fields_accessed TEXT[] NOT NULL,       -- ['name', 'email', 'document_number', ...]
    ip_address      TEXT,
    user_agent      TEXT,
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Append-only (mismo patrón que consent_audit_log)
REVOKE ALL ON public.pii_access_log FROM PUBLIC;
REVOKE ALL ON public.pii_access_log FROM authenticated;
REVOKE ALL ON public.pii_access_log FROM anon;

GRANT SELECT, INSERT ON public.pii_access_log TO service_role;

CREATE OR REPLACE FUNCTION public.pii_access_log_block_modify()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'pii_access_log es append-only (Ley 1581 Art. 9)';
END;
$$;

DROP TRIGGER IF EXISTS pii_access_log_no_update ON public.pii_access_log;
CREATE TRIGGER pii_access_log_no_update
    BEFORE UPDATE ON public.pii_access_log
    FOR EACH ROW EXECUTE FUNCTION public.pii_access_log_block_modify();

DROP TRIGGER IF EXISTS pii_access_log_no_delete ON public.pii_access_log;
CREATE TRIGGER pii_access_log_no_delete
    BEFORE DELETE ON public.pii_access_log
    FOR EACH ROW EXECUTE FUNCTION public.pii_access_log_block_modify();

-- RLS — tenant isolation.
ALTER TABLE public.pii_access_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_isolation_pii_access_log"
    ON public.pii_access_log;
CREATE POLICY "tenant_isolation_pii_access_log"
    ON public.pii_access_log
    FOR SELECT
    TO authenticated
    USING (
        tenant_id IN (
            SELECT tenant_id FROM public.tenant_users
            WHERE user_id = auth.uid()
        )
    );

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pii_access_log_tenant
    ON public.pii_access_log (tenant_id, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pii_access_log_contact
    ON public.pii_access_log (contact_id, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pii_access_log_actor
    ON public.pii_access_log (accessed_by, accessed_at DESC);

COMMENT ON TABLE public.pii_access_log IS
    'Habeas Data Ley 1581 Art. 9: log de accesos explícitos a PII de contacts. Append-only.';
