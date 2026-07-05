-- F5 bot_engine (decisión #1) — tenants nuevos nacen en el bot agentic.
--
-- NO aplicada aún: pendiente decisión/aplicación founder (ver docs/operations/onboarding-tenants.md
-- + feedback_supabase_migrations, el ledger tiene drift).
--
-- Contexto (dispatcher.is_tenant_agentic_enabled): sin un row dedicado
-- provider='agentic' con meta.agentic_enabled=true, un tenant cae por default al
-- bot LEGACY V1, cuyos prompts están brandeados KAIU hardcodeados — inaceptable
-- para un tenant distinto. El default False del dispatcher es intencional
-- (backward-compat del cutover de tenants viejos); el fix correcto es que el
-- ONBOARDING siembre el flag, no cambiar el default global.
--
-- Esta migración REEMPLAZA public.provision_tenant (firma 4-arg de la migración
-- 20260704120000_f3_provision_tenant_audit) añadiendo, dentro de la MISMA
-- transacción de provisión, el row tenant_integrations provider='agentic'
-- status='connected' meta={"agentic_enabled": true}. Aditivo y reversible: para
-- volver un tenant a legacy, UPDATE meta.agentic_enabled=false (o borrar el row).
--
-- Idempotencia: DROP FUNCTION IF EXISTS de ambas firmas históricas (3-arg y 4-arg)
-- + CREATE. El INSERT del row agentic usa ON CONFLICT (tenant_id, provider) DO
-- NOTHING (la tabla tiene UNIQUE(tenant_id, provider)).

DROP FUNCTION IF EXISTS public.provision_tenant(text, uuid, text);
DROP FUNCTION IF EXISTS public.provision_tenant(text, uuid, text, uuid);

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

  -- F5 decisión #1: nacer agentic. Row dedicado provider='agentic' (mismo patrón
  -- whatsapp/wompi/aveonline) leído por dispatcher.is_tenant_agentic_enabled.
  INSERT INTO public.tenant_integrations (tenant_id, provider, status, meta)
  VALUES (v_tenant_id, 'agentic', 'connected', jsonb_build_object('agentic_enabled', true))
  ON CONFLICT (tenant_id, provider) DO NOTHING;

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
      'agentic_enabled', true,
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
  'F3+F5: crea tenant + primer owner + subscripción + row tenant_integrations '
  'provider=agentic (agentic_enabled=true → nace en bot agentic, no legacy V1) + '
  'fila audit_log, todo en 1 transacción. Solo service_role (onboarding admin, no '
  'signup público). El usuario auth del owner debe existir antes (p_owner_user_id).';
