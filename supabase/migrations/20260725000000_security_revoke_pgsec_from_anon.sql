-- SEGURIDAD (CRÍTICO): el rol `anon` podía leer/escribir secretos de Vault de CUALQUIER tenant
-- sin autenticarse.
--
-- Causa raíz (dos condiciones que se combinan):
--   1. GRANTS: pgsec_read_secret / create / update / delete / upsert quedaron otorgadas a
--      PUBLIC y anon (nunca recibieron REVOKE; solo pgsec_list_secrets_by_name_pattern lo tuvo).
--   2. GUARD PERMISIVO: el cuerpo hace
--         IF auth.uid() IS NOT NULL THEN <check de ownership + rol owner/manager> END IF;
--         RETURN (SELECT decrypted_secret ...);
--      El guard se escribió así para que `service_role` (auth.uid() = NULL) pudiera pasar — pero
--      `anon` TAMBIÉN tiene auth.uid() = NULL, así que el bloque de ownership se SALTA ENTERO y
--      la función devuelve el secreto descifrado.
--
-- Impacto: con la llave publishable (que por diseño viaja en el bundle del navegador) y un UUID de
-- secreto, un tercero SIN sesión podía leer access_token/app_secret de WhatsApp, llaves privada y de
-- eventos de Wompi, y bot_token de Telegram — y con las de escritura, sobreescribirlos (p. ej. poner
-- su propio app_secret para firmar webhooks válidos e inyectar mensajes).
--
-- Fix (defensa en profundidad, sin romper los paths legítimos):
--   A. REVOKE EXECUTE a PUBLIC y anon. Los llamadores reales son:
--        - Server Actions de apps/web con sesión de usuario → rol `authenticated` (conserva EXECUTE;
--          para éstas auth.uid() NO es NULL, así que el check de ownership+rol SÍ aplica).
--        - Servicios backend → `service_role` (conserva EXECUTE; sigue pasando por diseño).
--   B. Rechazo explícito y fail-closed si el llamador es `anon`, por si un GRANT se re-otorga en el
--      futuro (p. ej. al recrear la función con CREATE OR REPLACE sin revocar). Aditivo: si
--      auth.role() no es 'anon' el comportamiento queda idéntico al actual.

-- ── A. Revocar el acceso de anon/PUBLIC ──────────────────────────────────────
-- Firmas verificadas contra prod (pg_proc.oid::regprocedure), no asumidas.
REVOKE ALL ON FUNCTION public.pgsec_read_secret(uuid)                    FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.pgsec_create_secret(text, text, text)      FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.pgsec_update_secret(uuid, text)            FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.pgsec_delete_secret(uuid)                  FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.pgsec_upsert_secret(text, text, text)      FROM PUBLIC, anon;

-- Re-afirmar explícitamente quién SÍ debe poder ejecutarlas (idempotente).
GRANT EXECUTE ON FUNCTION public.pgsec_read_secret(uuid)                 TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pgsec_create_secret(text, text, text)   TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pgsec_update_secret(uuid, text)         TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pgsec_delete_secret(uuid)               TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pgsec_upsert_secret(text, text, text)   TO authenticated, service_role;

-- ── B. Fail-closed dentro de la función de LECTURA (defensa en profundidad) ──
-- Cuerpo idéntico al de prod salvo el rechazo explícito de `anon` al inicio.
CREATE OR REPLACE FUNCTION public.pgsec_read_secret(p_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'vault', 'public', 'pg_catalog'
AS $function$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    -- Fail-closed: `anon` NUNCA puede leer secretos, aunque alguien re-otorgue el EXECUTE.
    -- (auth.role() lee el claim `role` del JWT de PostgREST: 'anon' | 'authenticated' | 'service_role'.
    --  Si es NULL — p. ej. llamada por SQL directo del admin — el comportamiento no cambia.)
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN NULL;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')   -- W1: NO operator
        ) THEN
            RETURN NULL;
        END IF;
    END IF;
    RETURN (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_id);
END;
$function$;

-- CREATE OR REPLACE re-otorga los defaults → volver a revocar y re-afirmar tras redefinir.
REVOKE ALL ON FUNCTION public.pgsec_read_secret(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.pgsec_read_secret(uuid) TO authenticated, service_role;

COMMENT ON FUNCTION public.pgsec_read_secret IS
  'Lee un secreto de Vault. anon SIN acceso (revocado + fail-closed). authenticated: solo owner/manager del tenant dueño del secreto. service_role: acceso backend.';
