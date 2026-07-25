-- W2a — Helper `app_current_role()`. PASO 1 de 3 del lockdown de escritura de dinero.
--
-- CAMBIO DE COMPORTAMIENTO: NINGUNO. Esta migración solo crea la función; ninguna policy la
-- usa todavía. Se separa a propósito para que, si algo falla con el helper, el diagnóstico
-- sea limpio (sin el ruido de 17 tablas cambiando a la vez).
--
-- Problema que habilita resolver: las policies de las tablas de dinero son
-- `FOR ALL USING (tenant_id = app_current_tenant())` — distinguen TENANT pero NO ROL. Como
-- `authenticated` conserva los GRANT de INSERT/UPDATE/DELETE, cualquier miembro del tenant
-- (incluido un `operator`, que es el empleado del Inbox) puede escribir por PostgREST:
-- cambiar `orders.total_amount`, marcar un pedido `confirmed` sin pago, crear un cupón 100% off,
-- mutar el ledger `stock_movements` o auto-subirse el `tenant_subscriptions.plan_code`.
-- Para escribir policies por rol hace falta un helper: hoy solo existe `app_current_tenant()`.
--
-- DECISIÓN DE DISEÑO — de dónde sale el rol:
--   Se lee FRESCO de `tenant_users`, NO del claim del JWT. Motivo: el claim queda obsoleto hasta
--   que el token se refresca (~1h), así que desactivar a un empleado no surtiría efecto inmediato.
--   Leyendo de la tabla, revocar el acceso es instantáneo.
--   Es SECURITY DEFINER a propósito: así NO evalúa las policies de `tenant_users` (evita
--   recursión de RLS: una policy que llama a una función que lee una tabla con RLS). Es seguro
--   porque solo devuelve el rol DEL PROPIO usuario (`auth.uid()`), nunca datos de terceros.
--   Se mantiene el override por GUC (`app.current_role`) por simetría con `app_current_tenant()`,
--   útil para workers que fijan contexto explícito.
--
-- NOTA: `service_role` tiene BYPASSRLS (verificado en prod: pg_roles.rolbypassrls = true), así que
-- los servicios backend NO se ven afectados por ninguna policy. El blast radius de todo este
-- lockdown es exclusivamente la consola web (rol `authenticated`).

CREATE OR REPLACE FUNCTION public.app_current_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $function$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_role', true), ''),
    (
      SELECT tu.role
      FROM public.tenant_users tu
      WHERE tu.user_id  = auth.uid()
        AND tu.tenant_id = public.app_current_tenant()
        AND tu.status    = 'active'
      LIMIT 1
    )
  );
$function$;

-- Norma del proyecto desde 20260725020000: ninguna función nace expuesta a anon.
REVOKE ALL ON FUNCTION public.app_current_role() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.app_current_role() TO authenticated, service_role;

COMMENT ON FUNCTION public.app_current_role() IS
  'Rol del usuario actual (owner|manager|operator) leído FRESCO de tenant_users para el tenant activo. SECURITY DEFINER para evitar recursión de RLS; solo devuelve el rol del propio auth.uid(). Devuelve NULL para service_role (que además bypassea RLS) y para sesiones sin membresía activa.';
