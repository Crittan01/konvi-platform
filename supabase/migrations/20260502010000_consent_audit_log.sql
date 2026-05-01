-- =============================================================================
-- Rev. 93 — Habeas Data Ley 1581 Art. 9: audit log inmutable de consent.
--
-- Append-only: REVOKE UPDATE/DELETE → solo INSERT y SELECT permitidos.
-- Permite al tenant responder a SIC con historial completo de eventos de
-- consent por contacto sin riesgo de manipulación retroactiva.
--
-- Eventos cubiertos:
--   • granted        — cliente otorgó consent (vía whatsapp / tenant_console).
--   • revoked        — cliente revocó (vía whatsapp / tenant_console).
--   • rectified      — cliente solicitó corrección de datos (Art. 16).
--   • export_request — cliente o tenant pidió export (Art. 14).
--   • portability    — cliente solicitó portabilidad (Art. 19).
--   • pii_access     — operador/agent accedió a PII (auditoría interna).
--
-- `phone_hash` (sha256 hex) en vez de phone literal para permitir lookup
-- post-revocación incluso después de que el contact_id sea anonimizado.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.consent_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    contact_id      UUID,                  -- NULL si row hard-deleted (preserva auditoría)
    phone_hash      TEXT,                  -- sha256 hex, lookup post-anonymization
    event           TEXT NOT NULL CHECK (event IN (
        'granted', 'revoked', 'rectified',
        'export_request', 'portability', 'pii_access'
    )),
    source          TEXT NOT NULL CHECK (source IN (
        'whatsapp', 'tenant_console', 'api', 'system'
    )),
    conversation_id UUID,
    actor_user_id   UUID,                  -- user_id si fue acción del tenant operator
    actor_email     TEXT,                  -- email del actor (caché para audit)
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- evidence shape sugerida:
    --   { "message_text": "elimina mis datos",
    --     "consent_version": "v2026-04",
    --     "fields_accessed": ["name","email"],
    --     "ip_address": "...",  // opcional
    --     "user_agent": "..."   // opcional
    --   }
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Append-only enforcement ─────────────────────────────────────────────────
-- service_role tiene acceso completo (necesario para inserts del backend).
-- PUBLIC: solo SELECT vía RLS. No UPDATE/DELETE para nadie excepto super.
REVOKE ALL ON public.consent_audit_log FROM PUBLIC;
REVOKE ALL ON public.consent_audit_log FROM authenticated;
REVOKE ALL ON public.consent_audit_log FROM anon;

GRANT SELECT, INSERT ON public.consent_audit_log TO service_role;

-- Trigger anti-tamper: bloquea UPDATE y DELETE incluso si alguien
-- accidentalmente otorga el privilegio.
CREATE OR REPLACE FUNCTION public.consent_audit_log_block_modify()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'consent_audit_log es append-only (Ley 1581 Art. 9)';
END;
$$;

DROP TRIGGER IF EXISTS consent_audit_log_no_update ON public.consent_audit_log;
CREATE TRIGGER consent_audit_log_no_update
    BEFORE UPDATE ON public.consent_audit_log
    FOR EACH ROW EXECUTE FUNCTION public.consent_audit_log_block_modify();

DROP TRIGGER IF EXISTS consent_audit_log_no_delete ON public.consent_audit_log;
CREATE TRIGGER consent_audit_log_no_delete
    BEFORE DELETE ON public.consent_audit_log
    FOR EACH ROW EXECUTE FUNCTION public.consent_audit_log_block_modify();

-- ── RLS — tenant isolation ──────────────────────────────────────────────────
ALTER TABLE public.consent_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_isolation_consent_audit_log"
    ON public.consent_audit_log;
CREATE POLICY "tenant_isolation_consent_audit_log"
    ON public.consent_audit_log
    FOR SELECT
    TO authenticated
    USING (
        tenant_id IN (
            SELECT tenant_id FROM public.tenant_users
            WHERE user_id = auth.uid()
        )
    );

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_consent_audit_log_tenant
    ON public.consent_audit_log (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_consent_audit_log_contact
    ON public.consent_audit_log (contact_id, occurred_at DESC)
    WHERE contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_consent_audit_log_phone_hash
    ON public.consent_audit_log (phone_hash)
    WHERE phone_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_consent_audit_log_event
    ON public.consent_audit_log (event, occurred_at DESC);

COMMENT ON TABLE public.consent_audit_log IS
    'Habeas Data Ley 1581 Art. 9: registro inmutable de eventos de consent. Append-only por triggers.';
