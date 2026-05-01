-- Rev. 101 (F3) — Vista unificada audit_log legacy + consent_audit_log.
--
-- Decisión: NO migrar data entre tablas. Cada una tiene su rol:
--   • audit_log (rev. 72)         — eventos genéricos CRUD via @audit_log decorator
--   • consent_audit_log (rev. 93) — eventos Habeas Data específicos (append-only)
-- Tocar data histórica en audit_log es destructivo y puede romper reportes
-- existentes. En su lugar, exponemos una vista que las une para uso del
-- operador / SIC reporting.
--
-- Casos de uso:
--   1. SIC pide "todos los eventos relacionados con un contacto" →
--      query a vw_consent_events_unified WHERE contact_id = X.
--   2. Reporte mensual de revocaciones → filter event_kind = 'revoked'.
--   3. Detección de inconsistencias (audit_log dice `consent_revoked`
--      pero no hay row en consent_audit_log) → comparison query.

CREATE OR REPLACE VIEW public.vw_consent_events_unified AS
-- ── Eventos canónicos del consent_audit_log (rev. 93+) ───────────────────────
SELECT
    cal.id,
    cal.tenant_id,
    cal.contact_id,
    cal.phone_hash,
    cal.event AS event_kind,
    cal.source,
    cal.actor_email,
    cal.actor_user_id,
    cal.evidence,
    cal.occurred_at,
    cal.created_at,
    'consent_audit_log'::TEXT AS origin_table
  FROM public.consent_audit_log cal

UNION ALL

-- ── Eventos legacy en audit_log relacionados con contacto/consent ────────────
-- Filtramos audit_log por entity_type='contact' Y action que mencione consent.
-- Esto cubre operaciones via @audit_log decorator antes de rev. 93 (cuando
-- el dev no migró el callsite a _log_consent_event explícito).
SELECT
    al.id,
    al.tenant_id,
    al.entity_id::UUID AS contact_id,
    NULL::TEXT AS phone_hash,
    -- Mapear action genérica a event_kind canónico cuando posible.
    CASE
        WHEN al.action ILIKE '%consent_given%' OR al.action ILIKE '%consent_granted%'
            THEN 'granted'
        WHEN al.action ILIKE '%consent_revok%' OR al.action ILIKE '%revoked%'
            THEN 'revoked'
        WHEN al.action ILIKE '%rectif%' OR al.action ILIKE '%updated%'
            THEN 'rectified'
        ELSE al.action
    END AS event_kind,
    'tenant_console'::TEXT AS source,
    al.user_email AS actor_email,
    al.user_id AS actor_user_id,
    al.payload AS evidence,
    al.created_at AS occurred_at,
    al.created_at,
    'audit_log'::TEXT AS origin_table
  FROM public.audit_log al
 WHERE al.entity_type = 'contact'
   AND (
       al.action ILIKE '%consent%'
    OR al.action ILIKE '%revok%'
    OR al.action ILIKE '%rectif%'
    OR al.action = 'deleted'  -- delete de contacto = supresión de facto
   );

-- ── RLS: la vista hereda RLS de las tablas subyacentes; no requiere policy
-- propia. SELECT del operador se filtra por tenant en cada lado.

GRANT SELECT ON public.vw_consent_events_unified TO authenticated, service_role;

COMMENT ON VIEW public.vw_consent_events_unified IS
    'Rev. 101 (F3) — Vista unificada de eventos consent: consent_audit_log '
    '(canónico rev. 93+) UNION audit_log (legacy filtrado entity_type=contact + '
    'action consent/revoke/rectify/delete). Usar en reportes SIC.';
