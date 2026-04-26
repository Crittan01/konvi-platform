-- Custom Access Token Hook para Supabase Auth
--
-- PROPÓSITO: Inyectar tenant_id, role y status en cada JWT emitido,
-- leyendo el estado ACTUAL de tenant_users. Reemplaza el trigger
-- on_tenant_assignment que actualizaba raw_app_meta_data manualmente.
--
-- BENEFICIOS:
-- - JWT siempre refleja el estado real (no puede quedar desactualizado)
-- - Cuando status='inactive' el JWT no lleva tenant_id → acceso bloqueado automáticamente
-- - Elimina la necesidad de llamar updateUserById(app_metadata) en cambios de rol
-- - Escala bien en ambientes pagos (Supabase Pro+)
--
-- INTERVENCION HUMANA REQUERIDA para activar el hook:
--   1. Supabase Dashboard → Authentication → Hooks
--   2. "Custom Access Token Hook" → Enable
--   3. Seleccionar: PostgreSQL Function → auth.custom_access_token_hook
--   4. Guardar
--
-- DESPUÉS de verificar que el hook funciona:
--   Aplicar: supabase/migrations/20260426080000_drop_tenant_assignment_trigger.sql

CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_tenant_id  text;
  v_role       text;
  v_claims     jsonb;
  v_app_meta   jsonb;
BEGIN
  -- Leer estado actual del miembro — solo si está activo
  SELECT
    tu.tenant_id::text,
    tu.role
  INTO v_tenant_id, v_role
  FROM public.tenant_users tu
  WHERE tu.user_id = (event->>'user_id')::uuid
    AND tu.status  = 'active'
  LIMIT 1;

  v_claims   := event->'claims';
  v_app_meta := COALESCE(v_claims->'app_metadata', '{}'::jsonb);

  IF v_tenant_id IS NOT NULL THEN
    -- Miembro activo — inyectar tenant_id y role en JWT
    v_app_meta := v_app_meta
      || jsonb_build_object('tenant_id', v_tenant_id)
      || jsonb_build_object('role',      v_role);
  ELSE
    -- Sin membresía activa — limpiar claims de tenant
    v_app_meta := v_app_meta - 'tenant_id' - 'role';
  END IF;

  v_claims := jsonb_set(v_claims, '{app_metadata}', v_app_meta);
  RETURN jsonb_set(event, '{claims}', v_claims);
END;
$$;

-- supabase_auth_admin necesita EXECUTE para llamar la función desde el hook
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;

-- Revocar acceso innecesario de roles no autorizados
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook
  FROM authenticated, anon;
