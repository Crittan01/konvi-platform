-- SEGURIDAD (CRÍTICO) — cierre de la CAUSA RAÍZ, no de un caso puntual.
--
-- La migración 20260725000000 cerró el bypass de `anon` sobre las funciones pgsec_* (secretos
-- de Vault). Auditando el resto del esquema aparecieron DOS hechos:
--
--   1. **38 funciones SECURITY DEFINER de `public` son ejecutables por `anon`** — el rol de la
--      llave publishable, que por diseño viaja en el bundle del navegador y NO requiere sesión.
--      Entre ellas: lectura de credenciales de integraciones, manipulación de inventario
--      (rpc_stock_*), retención/borrado de datos (fn_apply_retention), equipo del tenant
--      (get_tenant_team) y métricas de negocio (metrics_orders_*).
--
--   2. **`get_aveonline_credentials` repite EXACTAMENTE el bug de pgsec**:
--         IF auth.uid() IS NOT NULL THEN <check de pertenencia al tenant> END IF;
--         ... RETURN credenciales + password resuelto desde Vault
--      Escrito para que `service_role` (auth.uid() NULL) pasara; `anon` comparte esa propiedad
--      → el check se salta ENTERO. Es MÁS explotable que el de pgsec: recibe `p_tenant_id` como
--      PARÁMETRO (no hay que adivinar un UUID de secreto), y el tenant_id es semi-público —
--      va en la URL del webhook que se configura en Meta.
--
-- CAUSA RAÍZ: no existe `ALTER DEFAULT PRIVILEGES`, así que **toda función nueva nace con
-- EXECUTE para anon**. Se confirmó empíricamente: la función del trigger creada el 2026-07-24
-- recibió `GRANT ALL ... TO anon` automáticamente sin que ninguna migración lo pidiera.
--
-- FIX (3 capas):
--   A. Revocar PUBLIC+anon de TODAS las SECURITY DEFINER de `public` (dinámico: cubre las 38
--      y cualquiera que se haya agregado desde la auditoría).
--   B. Fail-closed explícito en get_aveonline_credentials (misma forma que pgsec_read_secret).
--   C. ALTER DEFAULT PRIVILEGES: las funciones FUTURAS ya no nacen expuestas a anon.
--
-- NO ROMPE NADA: verificado que los llamadores legítimos usan `authenticated` (consola web:
-- get_tenant_team, metrics_orders_summary, log_audit_export, pgsec_*, …) o `service_role`
-- (servicios Python), y que AMBOS roles tienen grants EXPLÍCITOS — revocar PUBLIC/anon los deja
-- intactos. Ningún llamador legítimo usa `anon` (sería un usuario sin sesión).
--
-- FUERA DE ALCANCE (siguiente ola, junto al RBAC de dinero): endurecer `authenticated`. Hoy un
-- usuario logueado puede invocar rpc_stock_* directamente; eso se corrige con policies por rol.

-- ── A. Revocar PUBLIC + anon de todas las SECURITY DEFINER de public ─────────
DO $$
DECLARE
  r record;
  n int := 0;
BEGIN
  FOR r IN
    SELECT p.oid::regprocedure::text AS sig
    FROM pg_proc p
    JOIN pg_namespace ns ON ns.oid = p.pronamespace
    WHERE ns.nspname = 'public' AND p.prosecdef
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM anon', r.sig);
    n := n + 1;
  END LOOP;
  RAISE NOTICE 'SECURITY DEFINER endurecidas (PUBLIC+anon revocados): %', n;
END $$;

-- ── B. Fail-closed en get_aveonline_credentials ──────────────────────────────
-- Cuerpo idéntico al de prod salvo el rechazo explícito de `anon` al inicio.
CREATE OR REPLACE FUNCTION public.get_aveonline_credentials(p_tenant_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'vault', 'pg_catalog'
AS $function$
DECLARE
    v_creds   JSONB;
    v_secret  TEXT;
    v_pass_id UUID;
BEGIN
    -- Fail-closed: `anon` NUNCA lee credenciales, aunque alguien re-otorgue el EXECUTE.
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    -- Verificación tenant_users (solo authenticated del tenant vía API).
    -- service_role bypasa porque maneja todos los tenants.
    IF auth.uid() IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = p_tenant_id AND user_id = auth.uid()
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT credentials INTO v_creds
    FROM public.tenant_integrations
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline'
      AND status = 'connected'
    LIMIT 1;

    IF v_creds IS NULL THEN
        RETURN NULL;
    END IF;

    -- Resolver password desde Vault (si está almacenado).
    v_pass_id := NULLIF(v_creds->>'password_secret_id', '')::uuid;
    IF v_pass_id IS NOT NULL THEN
        SELECT decrypted_secret INTO v_secret
        FROM vault.decrypted_secrets WHERE id = v_pass_id;
        IF v_secret IS NOT NULL THEN
            v_creds := v_creds || jsonb_build_object('password', v_secret);
        END IF;
    END IF;

    RETURN v_creds;
END;
$function$;

-- CREATE OR REPLACE re-otorga los defaults → revocar de nuevo tras redefinir.
REVOKE ALL ON FUNCTION public.get_aveonline_credentials(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_aveonline_credentials(uuid) TO authenticated, service_role;

-- ── C. CAUSA RAÍZ: las funciones futuras no nacen expuestas a anon ───────────
-- Sin esto, cualquier función nueva vuelve a recibir EXECUTE para anon y el problema reaparece.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

COMMENT ON FUNCTION public.get_aveonline_credentials IS
  'Devuelve credenciales Aveonline del tenant (password resuelto desde Vault). anon SIN acceso (revocado + fail-closed). authenticated: solo miembros del tenant. service_role: acceso backend.';
