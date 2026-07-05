-- F6 · Membresía single-tenant + JWT determinista (ADR-0030)
--
-- DECISIÓN (founder-aprobada, business_call impl_team_rbac): un usuario humano
-- pertenece a UN SOLO negocio (tenant). Konvi por ahora NO vende a operadores
-- que gestionen múltiples marcas con una misma cuenta. El schema permitía
-- multi-membresía (UNIQUE(user_id, tenant_id)) pero el custom_access_token_hook
-- usaba LIMIT 1 SIN ORDER BY → si un usuario tenía filas en 2 tenants, el JWT
-- elegía tenant de forma NO determinista (bug latente de seguridad/UX: podía
-- entrar al tenant equivocado). Este migration cierra ambos flancos:
--
--   (1) Hook JWT DETERMINISTA: ORDER BY estable (defensa en profundidad — correcto
--       aunque aún no exista el UNIQUE, p.ej. si el migration no se ha aplicado).
--   (2) add_member_to_tenant RECHAZA agregar un usuario que ya pertenece a OTRO
--       tenant (choke-point autoritativo: cubre invite existing-user + cualquier
--       caller service_role). Preserva el hardening F10 (search_path fijo).
--   (3) UNIQUE(user_id) — enforcement duro a nivel schema. Guardado: si ya hay
--       usuarios en >1 tenant, ABORTA con INTERVENCION HUMANA REQUERIDA en lugar
--       de fallar opaco (el migration NO se auto-aplica; esto es un gate seguro).
--
-- DEGRADACIÓN SEGURA: mientras este migration NO esté aplicado, el comportamiento
-- vigente se mantiene (multi-membresía tolerada + hook con ORDER BY sólo tras
-- aplicar). El frontend (team/page.tsx) pre-valida y muestra copy amigable, pero
-- la verdad la impone la DB aquí.
--
-- Ref: ADR-0030, ADR-0025 (aislamiento), F10 (20260703100000 secdef hardening).

-- ─── (1) Hook JWT determinista ────────────────────────────────────────────────
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
  -- Estado actual del miembro ACTIVO. ORDER BY determinista: con single-tenant
  -- hay a lo sumo 1 fila activa; el ORDER BY garantiza elección estable incluso
  -- si (transitoriamente, pre-UNIQUE) existieran varias — prioriza owner, luego
  -- la membresía más antigua, luego tenant_id, para un resultado reproducible.
  SELECT
    tu.tenant_id::text,
    tu.role
  INTO v_tenant_id, v_role
  FROM public.tenant_users tu
  WHERE tu.user_id = (event->>'user_id')::uuid
    AND tu.status  = 'active'
  ORDER BY
    CASE tu.role
      WHEN 'owner'    THEN 0
      WHEN 'manager'  THEN 1
      WHEN 'operator' THEN 2
      ELSE 3
    END,
    tu.created_at ASC,
    tu.tenant_id ASC
  LIMIT 1;

  v_claims   := event->'claims';
  v_app_meta := COALESCE(v_claims->'app_metadata', '{}'::jsonb);

  IF v_tenant_id IS NOT NULL THEN
    v_app_meta := v_app_meta
      || jsonb_build_object('tenant_id', v_tenant_id)
      || jsonb_build_object('role',      v_role);
  ELSE
    v_app_meta := v_app_meta - 'tenant_id' - 'role';
  END IF;

  v_claims := jsonb_set(v_claims, '{app_metadata}', v_app_meta);
  RETURN jsonb_set(event, '{claims}', v_claims);
END;
$$;

GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon;

-- ─── (2) add_member_to_tenant rechaza membresía cruzada ───────────────────────
CREATE OR REPLACE FUNCTION public.add_member_to_tenant(
  p_user_id   uuid,
  p_tenant_id uuid,
  p_role      text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF p_role NOT IN ('owner', 'manager', 'operator') THEN
    RAISE EXCEPTION 'Rol inválido: %', p_role;
  END IF;

  -- Single-tenant (ADR-0030): si el usuario ya pertenece a OTRO negocio, no se
  -- le puede agregar aquí. unique_violation (23505) para que el caller lo
  -- distinga de un fallo genérico.
  IF EXISTS (
    SELECT 1 FROM public.tenant_users
    WHERE user_id = p_user_id
      AND tenant_id <> p_tenant_id
  ) THEN
    RAISE EXCEPTION 'user_already_member_of_another_tenant'
      USING ERRCODE = 'unique_violation';
  END IF;

  INSERT INTO public.tenant_users (user_id, tenant_id, role)
  VALUES (p_user_id, p_tenant_id, p_role)
  ON CONFLICT (tenant_id, user_id) DO UPDATE
    SET role = EXCLUDED.role;
END;
$$;

COMMENT ON FUNCTION public.add_member_to_tenant IS
  'Inserta o actualiza un miembro en un tenant (roles: owner, manager, operator). '
  'ADR-0030: rechaza usuarios que ya pertenecen a otro tenant (single-tenant membership).';

-- ─── (3) UNIQUE(user_id) — enforcement duro, guardado ─────────────────────────
DO $guard$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tenant_users_user_id_unique'
  ) THEN
    IF EXISTS (
      SELECT 1 FROM public.tenant_users
      GROUP BY user_id
      HAVING count(*) > 1
    ) THEN
      RAISE EXCEPTION
        'INTERVENCION HUMANA REQUERIDA: existen usuarios en >1 tenant. '
        'Resolver membresías cruzadas antes de aplicar UNIQUE(user_id). Ver ADR-0030.';
    END IF;

    ALTER TABLE public.tenant_users
      ADD CONSTRAINT tenant_users_user_id_unique UNIQUE (user_id);
  END IF;
END
$guard$;
