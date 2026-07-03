-- FASE 0 seguridad (audit F10 · CRITICAL) — cierra escalada de privilegios cross-tenant.
--
-- add_member_to_tenant es SECURITY DEFINER (corre como postgres, salta RLS) y solo valida que
-- p_role ∈ (owner,manager,operator). Nunca se le hizo REVOKE → por default PostgreSQL concede EXECUTE a
-- PUBLIC y PostgREST la expone a anon/authenticated → CUALQUIER usuario (incluso anónimo) podía insertarse
-- como 'owner' en CUALQUIER tenant (envenenamiento de tenant_users → escalada a sesión con role=owner de
-- la víctima vía custom_access_token_hook). El único caller legítimo usa service_role (team/page.tsx admin
-- client), así que authenticated/anon no necesitan EXECUTE.
--
-- Fix (patrón ya usado en provision_tenant / fn_hard_delete_tenant / MFA): REVOKE de PUBLIC/anon/authenticated
-- + GRANT service_role + SET search_path fijo (hardening SECURITY DEFINER, CVE-2018-1058). Emitida con
-- timestamp posterior al último CREATE OR REPLACE (20260419000001) para que el REVOKE quede efectivo.
-- Ref: https://supabase.com/docs/guides/database/functions#security-definer-vs-invoker

REVOKE ALL ON FUNCTION public.add_member_to_tenant(uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.add_member_to_tenant(uuid, uuid, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.add_member_to_tenant(uuid, uuid, text) TO service_role;
ALTER FUNCTION public.add_member_to_tenant(uuid, uuid, text) SET search_path = public;
