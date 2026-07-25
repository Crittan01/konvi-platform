-- Fix del drift dual-source del onboarding.
--
-- El tenant_id/role del usuario viven en DOS lugares:
--   1. El claim del JWT — lo inyecta custom_access_token_hook leyendo tenant_users
--      (fuente de verdad) en cada emisión de token. Lo usan las RLS (auth.jwt()).
--   2. auth.users.raw_app_meta_data (el "stamp") — lo lee el dashboard vía
--      getUser().app_metadata (apps/web utils/supabase/cached-user.ts getCachedTenantMeta).
--
-- Problema: el stamp lo ponía SOLO provision_tenant (una vez, al crear el tenant) y
-- NUNCA se re-sincronizaba si cambiaba la membresía. Si a un usuario se lo remueve/
-- inactiva/reasigna (offboarding, add_member, cambio de rol), el stamp queda con el
-- tenant viejo → el dashboard (que lee el stamp) le seguiría dando acceso al tenant
-- anterior. Drift NO acotado (a diferencia del token, que al menos se re-evalúa al
-- refrescar).
--
-- Fix: un trigger AFTER INSERT/UPDATE/DELETE en tenant_users que recomputa la membresía
-- ACTIVA del usuario (misma lógica determinística que el hook) y estampa (o limpia)
-- raw_app_meta_data.tenant_id + role. Así el stamp queda sincronizado con tenant_users
-- INMEDIATAMENTE, sin tocar el path de auth de la app. Hace redundante (pero no rompe)
-- el stamp manual de provision_tenant.py (#159): ambos escriben el mismo valor.

CREATE OR REPLACE FUNCTION public.sync_tenant_stamp_to_auth()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'auth'
AS $function$
DECLARE
  v_user_id   uuid;
  v_tenant_id text;
  v_role      text;
BEGIN
  -- Usuario afectado: NEW en insert/update, OLD en delete.
  v_user_id := COALESCE(NEW.user_id, OLD.user_id);
  IF v_user_id IS NULL THEN
    RETURN COALESCE(NEW, OLD);
  END IF;

  -- Membresía ACTIVA actual — determinística (prioriza owner, luego la más antigua),
  -- idéntica a custom_access_token_hook para que stamp y token coincidan.
  SELECT tu.tenant_id::text, tu.role
  INTO v_tenant_id, v_role
  FROM public.tenant_users tu
  WHERE tu.user_id = v_user_id
    AND tu.status  = 'active'
  ORDER BY
    CASE tu.role WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 WHEN 'operator' THEN 2 ELSE 3 END,
    tu.created_at ASC,
    tu.tenant_id ASC
  LIMIT 1;

  IF v_tenant_id IS NOT NULL THEN
    UPDATE auth.users
    SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('tenant_id', v_tenant_id, 'role', v_role)
    WHERE id = v_user_id;
  ELSE
    -- Sin membresía activa (removido/inactivado): limpia el stamp → el dashboard deja de
    -- resolver el tenant viejo (cierra el hueco de acceso residual).
    UPDATE auth.users
    SET raw_app_meta_data = (COALESCE(raw_app_meta_data, '{}'::jsonb) - 'tenant_id' - 'role')
    WHERE id = v_user_id;
  END IF;

  -- Reasignación de membresía a otro usuario (OLD.user_id != NEW.user_id) es un caso que
  -- no ocurre en el flujo real; si algún día se hace, re-evaluar OLD.user_id aparte.
  RETURN COALESCE(NEW, OLD);
END;
$function$;

DROP TRIGGER IF EXISTS trg_sync_tenant_stamp ON public.tenant_users;
CREATE TRIGGER trg_sync_tenant_stamp
AFTER INSERT OR UPDATE OR DELETE ON public.tenant_users
FOR EACH ROW EXECUTE FUNCTION public.sync_tenant_stamp_to_auth();

COMMENT ON FUNCTION public.sync_tenant_stamp_to_auth IS
  'Mantiene auth.users.raw_app_meta_data.tenant_id/role en sync con la membresía activa de tenant_users (fix drift del stamp que lee el dashboard). Espeja custom_access_token_hook.';
