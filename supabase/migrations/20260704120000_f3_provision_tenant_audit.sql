-- F3 — audit trail atómico para la provisión de tenants (cierra gap "provisión sin audit trail").
--
-- NO aplicada aún: pendiente decisión/aplicación founder (ver docs/operations/onboarding-tenants.md).
-- Reemplaza public.provision_tenant para (a) recibir un actor opcional (quién provisiona) y (b) escribir
-- una fila en public.audit_log DENTRO de la misma transacción → el "quién/cuándo/qué" queda atómico con
-- la creación del tenant (no depende de un insert best-effort del script). Idempotencia de owner-duplicado
-- se mantiene en el script (scripts/admin/provision_tenant.py) para preservar el escape hatch
-- --allow-multi-tenant; aquí NO se agrega un guard que rompa ese flujo.
--
-- Firma NUEVA: se agrega p_actor_user_id (DEFAULT NULL). Se hace DROP de la firma vieja (3 args) para no
-- dejar dos overloads. El script llama con 3 args → resuelve por DEFAULT. Compatibilidad preservada.

DROP FUNCTION IF EXISTS public.provision_tenant(text, uuid, text);

CREATE OR REPLACE FUNCTION public.provision_tenant(
  p_tenant_name    text,
  p_owner_user_id  uuid,
  p_plan_code      text DEFAULT 'basic',
  p_actor_user_id  uuid DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant_id uuid;
  v_actor_email text;
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

  -- Audit trail atómico. actor = quien invoca (service_role vía script); snapshot de email si se conoce.
  IF p_actor_user_id IS NOT NULL THEN
    SELECT email INTO v_actor_email FROM auth.users WHERE id = p_actor_user_id;
  END IF;
  INSERT INTO public.audit_log (tenant_id, user_id, user_email, action, entity_type, entity_id, payload)
  VALUES (
    v_tenant_id, p_actor_user_id, v_actor_email, 'tenant.provisioned', 'tenant', v_tenant_id::text,
    jsonb_build_object(
      'owner_user_id', p_owner_user_id,
      'plan_code', COALESCE(NULLIF(btrim(p_plan_code), ''), 'basic'),
      'tenant_name', btrim(p_tenant_name),
      'via', 'provision_tenant_rpc'
    )
  );

  RETURN v_tenant_id;
END;
$$;

REVOKE ALL ON FUNCTION public.provision_tenant(text, uuid, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.provision_tenant(text, uuid, text, uuid) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.provision_tenant(text, uuid, text, uuid) TO service_role;

COMMENT ON FUNCTION public.provision_tenant(text, uuid, text, uuid) IS
  'F3: crea tenant + primer owner + subscripción + fila audit_log en 1 transacción. Solo service_role '
  '(onboarding admin, no signup público). El usuario auth del owner debe existir antes (p_owner_user_id). '
  'p_actor_user_id (opcional) = quién provisiona, para el audit trail.';
