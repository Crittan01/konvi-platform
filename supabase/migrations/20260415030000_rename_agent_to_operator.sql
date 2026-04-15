-- ============================================================
-- Migration: Renombrar rol 'agent' → 'operator' en tenant_users
-- Fecha: 2026-04-15
-- Motivo: UI usa owner/manager/operator — DB usaba owner/manager/agent
-- ============================================================

-- 1. Migrar datos existentes: agent → operator
UPDATE public.tenant_users
  SET role = 'operator'
  WHERE role = 'agent';

-- 2. Actualizar DEFAULT de la columna
ALTER TABLE public.tenant_users
  ALTER COLUMN role SET DEFAULT 'operator';

-- 3. Actualizar la función add_member_to_tenant para aceptar 'operator'
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
  -- Solo roles válidos (operator reemplaza a agent)
  IF p_role NOT IN ('owner', 'manager', 'operator') THEN
    RAISE EXCEPTION 'Rol inválido: %', p_role;
  END IF;

  INSERT INTO public.tenant_users (user_id, tenant_id, role)
  VALUES (p_user_id, p_tenant_id, p_role)
  ON CONFLICT (tenant_id, user_id) DO UPDATE
    SET role = EXCLUDED.role;
  -- El trigger on_tenant_assignment se dispara automáticamente
  -- e inyecta tenant_id + role en raw_app_meta_data del usuario
END;
$$;

COMMENT ON FUNCTION public.add_member_to_tenant IS
  'Inserta o actualiza un miembro en un tenant. Roles válidos: owner, manager, operator. Dispara on_tenant_assignment que inyecta JWT claims.';
