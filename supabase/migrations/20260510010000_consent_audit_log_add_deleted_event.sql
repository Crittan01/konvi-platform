-- =============================================================================
-- Rev. 103 (SaaS B2B pivot) — añadir event='deleted' al consent_audit_log.
--
-- Cuando el operador del tenant elimina físicamente un contact, registramos
-- el evento ANTES del DELETE para preservar trazabilidad ante SIC. El audit
-- log es append-only: la fila persiste indefinidamente con phone hasheado.
--
-- Source 'tenant_console' (ya existe en el CHECK actual) cubre el origen.
-- =============================================================================

ALTER TABLE public.consent_audit_log
    DROP CONSTRAINT IF EXISTS consent_audit_log_event_check;

ALTER TABLE public.consent_audit_log
    ADD CONSTRAINT consent_audit_log_event_check
    CHECK (event IN (
        'granted',
        'revoked',
        'rectified',
        'export_request',
        'portability',
        'pii_access',
        'deleted'
    ));

COMMENT ON CONSTRAINT consent_audit_log_event_check ON public.consent_audit_log IS
    'Eventos válidos del ciclo de vida del consent. Rev. 103 añade ''deleted'' '
    'para registrar borrado físico del contact (SaaS B2B model: tenant elimina, '
    'plataforma deja audit antes del DELETE).';
