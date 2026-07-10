-- =============================================================================
-- BLOQUE 0 · Seguridad P1 (2026-07-10) — audit_log APPEND-ONLY (tamper-evident).
--
-- HALLAZGO (auditoría FASE 0, verificado en HEAD): la única policy de audit_log es
-- `tenant_isolation_audit_log` FOR ALL (20260409260000_audit_log.sql:22), y no hay
-- REVOKE ni trigger anti-tamper. Por tanto CUALQUIER miembro autenticado del tenant
-- puede UPDATE/DELETE/forjar entradas del log de auditoría vía PostgREST directo →
-- el registro de auditoría no es confiable (viola el propósito de control).
--
-- FIX (dos propiedades: INMUTABILIDAD de filas escritas + NO-FORJA de atribución):
--   (1) REVOKE UPDATE, DELETE al rol `authenticated`/`anon`/PUBLIC → sin privilegio
--       de tabla, PostgREST no puede mutar filas ya escritas.
--   (2) Trigger BEFORE UPDATE/DELETE (defensa en profundidad si alguien re-otorga el
--       privilegio): rechaza la mutación cuando el rol del JWT es 'authenticated'/'anon'
--       (un miembro). service_role / procesos de sistema (retención) NO se bloquean, por
--       lo que la política de retención sigue pudiendo purgar filas viejas.
--   (3) Policy RESTRICTIVE FOR INSERT: un miembro CONSERVA INSERT — a diferencia de
--       consent_audit_log/pii_access_log (INSERT solo service_role), el frontend escribe
--       audit_log DIRECTO con el cliente `authenticated` (catalog/team/whatsapp/ai-agents/
--       insights/index-pending). Por eso NO se puede revocar INSERT sin romper el trail.
--       En su lugar se ata `user_id` al propio caller (auth.uid()) o NULL (sistema), para
--       que un miembro NO pueda forjar una entrada atribuida a OTRO usuario (p.ej. framing
--       del owner en una acción destructiva). La API escribe con service_role → bypassa RLS.
-- SELECT se conserva (RLS tenant_isolation sigue scopeando por tenant).
--
-- ⚠️ ALCANCE HONESTO: esto NO convierte audit_log en service_role-only. Un miembro aún
--    puede insertar una entrada VERAZ sobre SÍ MISMO o NULL-atribuida; lo que se cierra es
--    UPDATE/DELETE (inmutabilidad) y la atribución-a-otro (anti-framing). Migrar toda la
--    escritura de audit_log a service_role vía API queda como follow-up (fuera de BLOQUE 0).
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con el protocolo seguro (supabase db query --linked
--    + migration repair). Idempotente. Código degrada seguro (sin la migración, el log
--    sigue funcional pero mutable — este cambio solo lo endurece).
-- =============================================================================

REVOKE UPDATE, DELETE ON public.audit_log FROM authenticated, anon, PUBLIC;

CREATE OR REPLACE FUNCTION public.reject_audit_log_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    -- audit_log es append-only para los miembros del tenant. auth.role() lee el
    -- claim 'role' del JWT: 'authenticated'/'anon' = miembro → siempre rechazado.
    -- service_role / pg_cron / postgres (retención) → auth.role() NULL o 'service_role'
    -- → permitido (la retención necesita DELETE de filas fuera de ventana).
    IF COALESCE(auth.role(), '') IN ('authenticated', 'anon') THEN
        RAISE EXCEPTION 'audit_log es append-only: % no permitido para miembros', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_log_append_only ON public.audit_log;
CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON public.audit_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_log_mutation();

COMMENT ON FUNCTION public.reject_audit_log_mutation() IS
    'BLOQUE 0 — audit_log append-only: rechaza UPDATE/DELETE de miembros (auth.role authenticated/anon). service_role/retención permitidos.';

-- (3) Anti-forja de atribución. RESTRICTIVE se AND-ea con la policy permisiva existente
--     `tenant_isolation_audit_log` (WITH CHECK tenant_id = app_current_tenant()): el INSERT
--     de un miembro debe cumplir AMBAS. user_id NULL (sistema/no resuelto) se permite; un
--     user_id concreto debe ser el propio caller. auth.uid() = sub del JWT (= user_id que el
--     frontend setea al actor). service_role bypassa RLS → no afectado.
DROP POLICY IF EXISTS audit_log_insert_self_attribution ON public.audit_log;
CREATE POLICY audit_log_insert_self_attribution ON public.audit_log
    AS RESTRICTIVE
    FOR INSERT
    TO authenticated
    WITH CHECK (user_id IS NULL OR user_id = (SELECT auth.uid()));

COMMENT ON POLICY audit_log_insert_self_attribution ON public.audit_log IS
    'BLOQUE 0 — anti-forja: un miembro solo puede insertar entradas con user_id propio (auth.uid()) o NULL; no puede atribuir una acción a otro usuario. Escritura de servidor va por service_role (bypassa RLS).';
