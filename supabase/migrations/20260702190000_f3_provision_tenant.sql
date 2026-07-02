-- F3 activación — provisión transaccional de un tenant nuevo (onboarding ADMIN-controlado, decisión founder).
--
-- Crea en UNA transacción: tenant + primer owner (tenant_users) + subscripción por defecto. Atómico: si algo
-- falla, no queda tenant huérfano ni owner sin tenant. NO es signup público — solo lo invoca el service_role
-- (el script admin), tras crear el usuario auth. El app defaultea plan 'basic' si no hay subscripción, pero la
-- creamos explícita para trazabilidad de plan.
--
-- SECURITY DEFINER + REVOKE public/authenticated + GRANT service_role: ningún usuario final puede auto-provisionar
-- tenants (evita superficie de abuso). role/status validados contra los CHECK reales (owner/manager/operator ·
-- active/inactive).

CREATE OR REPLACE FUNCTION public.provision_tenant(
  p_tenant_name    text,
  p_owner_user_id  uuid,
  p_plan_code      text DEFAULT 'basic'
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant_id uuid;
BEGIN
  IF p_tenant_name IS NULL OR length(btrim(p_tenant_name)) = 0 THEN
    RAISE EXCEPTION 'provision_tenant: p_tenant_name requerido';
  END IF;
  IF p_owner_user_id IS NULL THEN
    RAISE EXCEPTION 'provision_tenant: p_owner_user_id requerido (crea el usuario auth primero)';
  END IF;

  INSERT INTO public.tenants (name)
  VALUES (btrim(p_tenant_name))
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_users (user_id, tenant_id, role, status)
  VALUES (p_owner_user_id, v_tenant_id, 'owner', 'active');

  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status)
  VALUES (v_tenant_id, COALESCE(NULLIF(btrim(p_plan_code), ''), 'basic'), 'active');

  RETURN v_tenant_id;
END;
$$;

REVOKE ALL ON FUNCTION public.provision_tenant(text, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.provision_tenant(text, uuid, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.provision_tenant(text, uuid, text) TO service_role;

COMMENT ON FUNCTION public.provision_tenant IS
  'F3: crea tenant + primer owner + subscripción en 1 transacción. Solo service_role (onboarding admin, '
  'no signup público). El usuario auth del owner debe existir antes (p_owner_user_id).';
