-- =============================================================================
-- BLOQUE 0 · Seguridad P1 (2026-07-10) — pii_access_log: GRANT SELECT a authenticated.
--
-- HALLAZGO (auditoría FASE 0, verificado en HEAD): la pestaña "Accesos a datos
-- personales" (Auditoría) lee pii_access_log desde el cliente autenticado, pero la
-- migración canónica 20260502010001_pii_access_log.sql:29 hace REVOKE ALL FROM
-- authenticated y el único GRANT (línea 32) es a service_role. La policy RLS
-- `tenant_isolation_pii_access_log` FOR SELECT TO authenticated (líneas 58-67) NO
-- sustituye el privilegio de tabla → el SELECT del operador falla y la pestaña queda
-- rota (Habeas Data: el titular/operador no puede ver el log de accesos a PII).
--
-- FIX: GRANT SELECT (solo SELECT) a authenticated → la policy RLS existente por fin
-- aplica (scoping por membresía tenant_users). INSERT/UPDATE/DELETE siguen restringidos
-- a service_role; los triggers append-only + RLS tenant_isolation siguen protegiendo.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. Idempotente.
-- =============================================================================

GRANT SELECT ON public.pii_access_log TO authenticated;
