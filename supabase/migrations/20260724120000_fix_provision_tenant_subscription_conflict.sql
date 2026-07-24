-- Fix: provision_tenant fallaba con duplicate key en tenant_subscriptions → onboarding ROTO.
--
-- Causa: el trigger trg_seed_tenant_subscription_default (20260420000005_plan_tiering_foundation)
-- auto-inserta un tenant_subscriptions (plan 'basic', ON CONFLICT DO NOTHING) en cada INSERT de
-- tenants. Este RPC luego RE-inserta la subscription SIN ON CONFLICT → colisión con la fila del
-- trigger → `duplicate key value violates unique constraint "tenant_subscriptions_tenant_id_key"`
-- → la transacción del RPC hace rollback → todo provision de tenant nuevo falla (determinístico).
--
-- Descubierto empíricamente 2026-07-24. Nota: al INSERT de tenant_integrations SÍ le pusieron
-- ON CONFLICT; a subscriptions se les olvidó.
--
-- Fix: ON CONFLICT (tenant_id) DO UPDATE en el insert de subscription — el plan elegido por el
-- RPC (p_plan_code) gana sobre el 'basic' que fija el trigger, preservando la semántica del RPC.
--
-- El cuerpo replica la definición REAL de prod (verificada vía pg_get_functiondef = f5);
-- el ÚNICO cambio funcional es el ON CONFLICT en el insert de tenant_subscriptions.

CREATE OR REPLACE FUNCTION public.provision_tenant(
  p_tenant_name text,
  p_owner_user_id uuid,
  p_plan_code text DEFAULT 'basic'::text,
  p_actor_user_id uuid DEFAULT NULL::uuid
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
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

  -- FIX: el trigger trg_seed_tenant_subscription_default ya insertó una fila 'basic' al crear el
  -- tenant. ON CONFLICT DO UPDATE hace que el plan elegido por el RPC prevalezca (antes: duplicate).
  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status)
  VALUES (v_tenant_id, COALESCE(NULLIF(btrim(p_plan_code), ''), 'basic'), 'active')
  ON CONFLICT (tenant_id) DO UPDATE
    SET plan_code = EXCLUDED.plan_code,
        status = EXCLUDED.status;

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
$function$;
