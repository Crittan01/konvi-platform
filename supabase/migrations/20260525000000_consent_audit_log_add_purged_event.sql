-- =============================================================================
-- Sem 7 F2 cierre 2026-05-19 — añadir event='purged' al consent_audit_log.
--
-- Bug founder UAT 2026-05-19 (conv 056490b8): tras eliminar contact desde UI,
-- carts/conversations/orders quedaban huérfanos en DB porque el server action
-- hacía DELETE simple sin cascade. El cart-recovery flow rev. 70 los
-- recuperaba en próximas conversaciones del mismo phone → cart contaminado.
--
-- Fix arquitectónico (commit 17d3dd3): nuevo endpoint
--   POST /api/v1/contacts/{id}/purge
-- que ejecuta cascade completo vía helper `lib.contact_cleanup.purge_contact_completely`.
--
-- Diferenciación semántica vs `event='deleted'` (migración 20260510010000):
--   • 'deleted' → soft-delete con anonimización (Ley 1581 Art. 15 — preserva
--                  phone + orders + audit). Para PRODUCCIÓN regular.
--   • 'purged'  → HARD-DELETE en cascade (borra contact + conversations +
--                  carts + orders). Para TESTING/admin del owner.
--
-- Mantener ambos eventos permite distinguir en auditorías SIC el camino real
-- ejercido por el operador.
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
        'deleted',
        'purged'
    ));

COMMENT ON CONSTRAINT consent_audit_log_event_check ON public.consent_audit_log IS
    'Eventos válidos del ciclo de vida del consent. Sem 7 F2 cierre 2026-05-19 '
    'añade ''purged'' para hard-delete cascade (uso testing/admin) — distinto de '
    '''deleted'' (anonimización soft Habeas Data Art. 15).';
