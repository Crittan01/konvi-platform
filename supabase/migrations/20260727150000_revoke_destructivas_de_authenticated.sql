-- ═══════════════════════════════════════════════════════════════════════════
-- Un usuario logueado podía borrar los mensajes de TODOS los tenants.
--
-- CÓMO SE ENCONTRÓ
-- Auditando las superficies desplegadas hoy (#195/#197) con una lente transversal.
-- No es un defecto de ese código: es la deuda que la migración 20260725020000 dejó
-- escrita como "fuera de alcance, siguiente ola" al final de su encabezado —
-- «endurecer `authenticated`. Hoy un usuario logueado puede invocar rpc_stock_*
-- directamente». Esta es esa ola, para el subconjunto que destruye datos.
--
-- LO QUE ESTABA ABIERTO, verificado contra producción el 2026-07-27:
--
--     has_function_privilege('authenticated',
--         'public.fn_apply_retention(text,boolean)', 'EXECUTE')  →  TRUE
--
-- `fn_apply_retention` es SECURITY DEFINER, **no valida absolutamente nada** —ni
-- pertenencia al tenant ni rol— y su bucle recorre `public.tenants` ENTERA:
--
--     FOR r_tenant IN SELECT id AS tenant_id FROM public.tenants LOOP
--         DELETE FROM public.messages WHERE tenant_id = r_tenant.tenant_id AND ...
--
-- O sea que cualquier usuario con sesión de CUALQUIER tenant —un operador, el
-- empleado de otro comerciante de la plataforma— podía invocarla por PostgREST con
-- `p_dry_run := false` y borrar los mensajes, las conversaciones y los contactos de
-- todos los demás. Con lo desplegado hoy eso incluye la prueba del contrato que la
-- ley obliga a conservar diez años.
--
-- CAUSA RAÍZ, otra vez la misma: sin `ALTER DEFAULT PRIVILEGES` para `authenticated`,
-- toda función nace con EXECUTE para ese rol. La migración original solo concedía a
-- `service_role`; el grant a `authenticated` nunca lo pidió nadie. Es exactamente el
-- mecanismo de #162/#164, un rol más arriba.
--
-- ── POR QUÉ ESTAS CINCO Y NO TODAS ─────────────────────────────────────────
-- Revocar `authenticated` en bloque de todas las SECURITY DEFINER rompería la consola:
-- hay funciones que la web SÍ invoca con la sesión del usuario y que sí validan
-- pertenencia (`get_tenant_team`, `metrics_orders_*`, `pgsec_*`). Se cierra el
-- subconjunto que cumple LAS DOS condiciones:
--   · destruye filas (DELETE/TRUNCATE), y
--   · no tiene ninguna guarda de pertenencia.
--
-- `pgsec_delete_secret` queda como está a propósito: la consola la llama con la
-- sesión del usuario al desconectar una integración, y sí verifica que quien llama
-- sea owner/manager del tenant DUEÑO del secreto.
--
-- Se verificó llamador por llamador que ninguna de las cinco se invoca desde
-- `apps/web` con sesión de usuario: todas viven en el worker o en routers del API,
-- que usan `service_role`.
-- ═══════════════════════════════════════════════════════════════════════════

REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_purge_orphan_shipment_quotes(INTEGER) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.cleanup_expired_idempotency_keys(INTEGER) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.cleanup_expired_rate_limit_windows(INTEGER) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.outbound_idempotency_cleanup() FROM authenticated;

-- Y explícito para PUBLIC, que es de donde el grant vuelve a colarse si alguien
-- re-crea la función con CREATE OR REPLACE desde una versión vieja del repo.
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_purge_orphan_shipment_quotes(INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.cleanup_expired_idempotency_keys(INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.cleanup_expired_rate_limit_windows(INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.outbound_idempotency_cleanup() FROM PUBLIC;

COMMENT ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) IS
    'Barrido de retención. SOLO service_role: recorre todos los tenants y borra sin '
    'validar pertenencia, así que un GRANT a authenticated es borrado cross-tenant. '
    'Lo tenía hasta el 2026-07-27 por privilegios por defecto del esquema.';
