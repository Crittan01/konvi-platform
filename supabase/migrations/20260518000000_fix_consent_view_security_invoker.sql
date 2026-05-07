-- =============================================================================
-- SECURITY FIX — Habeas Data CVE potential (rev. 105)
-- Fecha: 2026-05-07
-- Disparador: Supabase Advisor reportó CRITICAL — view
-- vw_consent_events_unified tiene SECURITY DEFINER (default Postgres 15
-- pre security_invoker option).
--
-- IMPACTO PRE-FIX:
--   La view fue creada en migration 20260509010000 SIN
--   `WITH (security_invoker=true)`. Default behavior en PG: view ejecuta
--   con permisos del OWNER (postgres superuser) — bypassing RLS de las
--   tablas subyacentes (consent_audit_log + audit_log).
--
--   En consecuencia: cualquier usuario `authenticated` con GRANT SELECT
--   sobre la view (todos los tenant users lo tienen) podía consultar
--   `SELECT * FROM vw_consent_events_unified WHERE tenant_id = X` con X
--   = OTRO tenant_id, y ver eventos consent + audit de OTROS TENANTS.
--   Esto VIOLA Habeas Data Ley 1581 Art. 4 (responsabilidad
--   demostrada) + Art. 9 (audit log integridad).
--
-- FIX:
--   Recrear la view con `WITH (security_invoker=true)` (Postgres 15+).
--   Esto fuerza que SELECT ejecute con permisos del USUARIO actual,
--   respetando las RLS policies de `consent_audit_log` y `audit_log`
--   (ambas tienen Tenant Isolation policies).
--
-- VERIFICACIÓN POST-MIGRATION:
--   1. SELECT pg_class.reloptions FROM pg_class WHERE relname=...
--      → debe contener {security_invoker=true}.
--   2. Como user authenticated tenant A, SELECT * → solo rows del
--      tenant A (RLS aplica naturalmente).
--   3. Como service_role (no afectado por RLS), ve TODO igual que antes.
-- =============================================================================

-- Recrear view con security_invoker explícito.
-- DROP+CREATE en lugar de ALTER porque PG no soporta ALTER VIEW SET
-- (security_invoker) en algunas versiones edge case.

DROP VIEW IF EXISTS public.vw_consent_events_unified;

CREATE VIEW public.vw_consent_events_unified
    WITH (security_invoker = true)
AS
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
SELECT
    al.id,
    al.tenant_id,
    al.entity_id::UUID AS contact_id,
    NULL::TEXT AS phone_hash,
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
    OR al.action = 'deleted'
   );

-- Re-aplicar GRANTs (DROP VIEW los borró).
GRANT SELECT ON public.vw_consent_events_unified TO authenticated, service_role;

COMMENT ON VIEW public.vw_consent_events_unified IS
    'Rev. 101 (F3) — Vista unificada eventos consent. Sem 5 H.fix-cve '
    '(rev. 105 2026-05-07): recreada con security_invoker=true para '
    'respetar RLS Tenant Isolation. Pre-fix bypassaba RLS al ejecutar '
    'como owner postgres (CVE Habeas Data potential).';
