-- ⚠️ APLICAR SOLO DESPUÉS DE VERIFICAR QUE EL HOOK FUNCIONA CORRECTAMENTE
--
-- Este script elimina el trigger on_tenant_assignment que actualizaba
-- raw_app_meta_data manualmente. El Custom Access Token Hook lo reemplaza.
--
-- CRITERIO DE ÉXITO ANTES DE APLICAR:
-- 1. El hook está registrado en Dashboard → Auth → Hooks
-- 2. Iniciar sesión como un miembro del equipo y verificar:
--    SELECT (auth.jwt()->'app_metadata'->>'tenant_id') = '<tu-tenant-id>';
-- 3. Cambiar el rol de un miembro → signOut → volver a entrar → verificar nuevo rol en JWT
-- 4. Inactivar un miembro → no puede acceder al dashboard
--
-- CÓMO APLICAR:
--   supabase db query --linked -f supabase/migrations/20260426080000_drop_tenant_assignment_trigger.sql

-- Eliminar el trigger (la función se mantiene por si acaso durante el período de transición)
DROP TRIGGER IF EXISTS on_tenant_assignment ON public.tenant_users;

-- La función puede eliminarse también una vez confirmado que el hook es estable:
-- DROP FUNCTION IF EXISTS public.handle_tenant_assignment();

COMMENT ON FUNCTION public.custom_access_token_hook IS
  'Hook activo desde 2026-04-26. Reemplaza trigger on_tenant_assignment.';
