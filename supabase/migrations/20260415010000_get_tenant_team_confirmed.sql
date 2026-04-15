-- ============================================================
-- Migration: get_tenant_team devuelve confirmed status
-- Para mostrar miembros pendientes de confirmacion en la UI
-- Fecha: 2026-04-15
-- ============================================================

-- DROP requerido: PostgreSQL no permite CREATE OR REPLACE si cambia el tipo de retorno
DROP FUNCTION IF EXISTS get_tenant_team();

CREATE OR REPLACE FUNCTION get_tenant_team()
RETURNS TABLE (
    user_id   uuid,
    email     text,
    role      text,
    joined_at timestamptz,
    confirmed boolean
)
LANGUAGE plpgsql SECURITY DEFINER
-- search_path explícito requerido en Supabase Cloud para acceder a auth.users y auth.jwt()
-- dentro del contexto SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_tenant_id uuid;
BEGIN
  -- Leer tenant_id del JWT del usuario que llama
  v_tenant_id := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid;

  IF v_tenant_id IS NULL THEN
    RETURN; -- Sin contexto de tenant, retornar vacío en lugar de error
  END IF;

  RETURN QUERY
  SELECT
    tu.user_id,
    au.email::text,
    tu.role::text,
    tu.created_at AS joined_at,
    (au.email_confirmed_at IS NOT NULL) AS confirmed
  FROM public.tenant_users tu
  JOIN auth.users au ON au.id = tu.user_id
  WHERE tu.tenant_id = v_tenant_id
  ORDER BY tu.created_at ASC;
END;
$$;

-- Grant explícito para rol authenticated
GRANT EXECUTE ON FUNCTION get_tenant_team() TO authenticated;
