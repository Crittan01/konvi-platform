-- Convergencia auth (runbook docs/runbooks/converge-auth-claims-hook.md).
-- Retira la mecánica LEGACY de claims. El hook custom_access_token_hook ya es la
-- fuente viva del claim app_metadata.tenant_id/role (habilitado + verificado en
-- prod 2026-07-16: 3/3 usuarios OK, login Render OK). El trigger quedó redundante
-- (el hook lee tenant_users con status='active' y sobrescribe el claim en cada
-- emisión de token, sin depender de raw_app_meta_data que el trigger escribía).
-- Idempotente para el replay (el trigger ya está ausente desde 20260426080000;
-- acá se elimina también la función, que ninguna otra migración referencia).
DROP TRIGGER IF EXISTS on_tenant_assignment ON public.tenant_users;
DROP FUNCTION IF EXISTS public.handle_new_user_claims();
