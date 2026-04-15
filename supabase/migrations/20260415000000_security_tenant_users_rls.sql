-- ============================================================
-- Migration: Security hardening tenant_users
-- Fecha: 2026-04-15
-- Vuelta: Cierre Configuración — Seguridad
-- ============================================================

-- 1. Habilitar RLS en tenant_users (estaba sin políticas)
ALTER TABLE public.tenant_users ENABLE ROW LEVEL SECURITY;

-- 2. Política: un usuario solo puede ver los miembros de SU tenant
CREATE POLICY "Tenant Isolation — tenant_users"
  ON public.tenant_users
  FOR ALL
  USING (tenant_id = app_current_tenant());

-- 3. Unique constraint: un usuario no puede pertenecer dos veces al mismo tenant
ALTER TABLE public.tenant_users
  ADD CONSTRAINT tenant_users_tenant_user_unique
  UNIQUE (tenant_id, user_id);

-- 4. Index de apoyo para get_tenant_team (performance)
CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant_id
  ON public.tenant_users (tenant_id);

-- 5. Función helper: invite_member_to_tenant
--    Usada por el trigger para que el Server Action pueda insertar
--    el nuevo miembro sin violar RLS (se ejecuta como SECURITY DEFINER)
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
  -- Solo roles válidos
  IF p_role NOT IN ('owner', 'manager', 'agent') THEN
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

-- Comentario de trazabilidad
COMMENT ON FUNCTION public.add_member_to_tenant IS
  'Inserta o actualiza un miembro en un tenant. Dispara on_tenant_assignment que inyecta JWT claims. Usada por el invite flow de Configuración > Usuarios y Acceso.';
