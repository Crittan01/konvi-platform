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
LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    RETURN QUERY
    SELECT
        tu.user_id,
        au.email,
        tu.role,
        tu.created_at AS joined_at,
        (au.email_confirmed_at IS NOT NULL) AS confirmed
    FROM public.tenant_users tu
    JOIN auth.users au ON au.id = tu.user_id
    WHERE tu.tenant_id = app_current_tenant()
    ORDER BY tu.created_at ASC;
END;
$$;
