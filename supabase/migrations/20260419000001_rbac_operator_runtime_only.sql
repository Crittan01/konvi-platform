-- ============================================================================
-- RBAC runtime normalization: owner | manager | operator
-- Date: 2026-04-19
-- ============================================================================

-- Backfill legacy values.
UPDATE public.tenant_users
SET role = 'operator'
WHERE role = 'agent'
   OR role IS NULL
   OR role NOT IN ('owner', 'manager', 'operator');

ALTER TABLE public.tenant_users
  ALTER COLUMN role SET DEFAULT 'operator';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tenant_users_role_check'
      AND conrelid = 'public.tenant_users'::regclass
  ) THEN
    ALTER TABLE public.tenant_users DROP CONSTRAINT tenant_users_role_check;
  END IF;
END
$$;

ALTER TABLE public.tenant_users
  ADD CONSTRAINT tenant_users_role_check
  CHECK (role IN ('owner', 'manager', 'operator'));

CREATE OR REPLACE FUNCTION public.add_member_to_tenant(
  p_user_id   uuid,
  p_tenant_id uuid,
  p_role      text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  IF p_role NOT IN ('owner', 'manager', 'operator') THEN
    RAISE EXCEPTION 'Rol inválido: %', p_role;
  END IF;

  INSERT INTO public.tenant_users (user_id, tenant_id, role)
  VALUES (p_user_id, p_tenant_id, p_role)
  ON CONFLICT (tenant_id, user_id) DO UPDATE
    SET role = EXCLUDED.role;
END;
$$;

COMMENT ON FUNCTION public.add_member_to_tenant IS
  'Inserta o actualiza un miembro en un tenant. Roles runtime válidos: owner, manager, operator.';
