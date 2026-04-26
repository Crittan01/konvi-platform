-- Migración: estados activo/inactivo para miembros del equipo
-- Permite suspender temporalmente el acceso sin eliminar el vínculo con el tenant.

ALTER TABLE public.tenant_users
  ADD COLUMN IF NOT EXISTS status             TEXT NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS inactivated_at     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS inactivated_reason TEXT,
  ADD COLUMN IF NOT EXISTS inactivated_by     UUID REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.tenant_users
  ADD CONSTRAINT tenant_users_status_check
  CHECK (status IN ('active', 'inactive'));

COMMENT ON COLUMN public.tenant_users.status IS
  'active: acceso normal | inactive: suspendido temporalmente';
COMMENT ON COLUMN public.tenant_users.inactivated_reason IS
  'Motivo de suspensión (ej: vacaciones, baja temporal). Opcional.';

-- Actualizar get_tenant_team para incluir status
DROP FUNCTION IF EXISTS public.get_tenant_team();
CREATE OR REPLACE FUNCTION public.get_tenant_team()
RETURNS TABLE (
    user_id      uuid,
    email        text,
    role         text,
    status       text,
    joined_at    timestamptz,
    confirmed    boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public, auth
AS $$
    SELECT
        tu.user_id,
        u.email,
        tu.role,
        tu.status,
        tu.created_at  AS joined_at,
        (u.email_confirmed_at IS NOT NULL) AS confirmed
    FROM public.tenant_users tu
    JOIN auth.users u ON u.id = tu.user_id
    WHERE tu.tenant_id = (
        (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    )
    ORDER BY tu.created_at ASC;
$$;
