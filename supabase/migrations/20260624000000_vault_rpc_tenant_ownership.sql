-- ============================================================
-- A6.4 finiquito — Vault RPC tenant ownership validation
-- Fecha: 2026-06-24
-- Branch: feat/A6-A7-quality-first-rev111
-- ============================================================
--
-- PROBLEMA (super-audit + análisis profundo 2026-06-24):
--   pgsec_read_secret / pgsec_update_secret / pgsec_delete_secret /
--   pgsec_upsert_secret / pgsec_create_secret están GRANT ... TO authenticated
--   y NO validan que el caller sea dueño del secret. El frontend
--   (apps/web/.../integrations/page.tsx, lib/aveonline-actions.ts) los llama
--   directo con el JWT del usuario. Si un secret_id (UUID) de otro tenant se
--   filtra (logs, soporte, error message), cualquier usuario autenticado podía
--   LEER/SOBRESCRIBIR/BORRAR la credencial de otro tenant (token WhatsApp,
--   llave privada Wompi, bot_token Telegram).
--
-- SOLUCIÓN (mínima, sigue el precedente get_aveonline_credentials):
--   El NOMBRE del secret ya codifica el tenant dueño:
--   `{tenant_id}::text || '/' || provider || '/' || credential`
--   (ver 20260426020000 backfill + page.tsx + aveonline-actions.ts).
--   Por tanto NO se necesita tabla metadata ni dual-read. Cada RPC:
--     1. Deriva el tenant dueño del nombre (split_part(name,'/',1)::uuid).
--     2. Si auth.uid() IS NOT NULL (= caller authenticated, no service_role):
--        exige que el user sea miembro de ese tenant (public.tenant_users).
--     3. service_role (auth.uid() NULL) BYPASA — maneja todos los tenants,
--        igual que get_aveonline_credentials (20260527020000).
--   Secrets con nombre legacy sin prefijo tenant → rechazados a authenticated
--   (solo service_role puede tocarlos; el backfill ya prefija todos los activos).
--
-- COMPATIBILIDAD: los GRANT no cambian (authenticated + service_role); el gate
--   vive DENTRO de la función. El frontend legítimo siempre usa su propio
--   tenant_id en el nombre → nunca dispara el rechazo. service_role intacto.
--
-- INTERVENCION HUMANA REQUERIDA — aplicar a producción:
--   RESPONSABLE: founder + DevOps.
--   PASOS: (1) aplicar en dev/staging primero. (2) verificar lectura/escritura
--          del PROPIO secret OK (UI integraciones conecta/desconecta WhatsApp/
--          Wompi/Telegram/Aveonline/MeLi). (3) verificar bot envía WhatsApp
--          (backend service_role lee token OK). (4) test cross-tenant: con JWT
--          tenant A, llamar pgsec_read_secret(secret_id_de_B) → debe retornar
--          NULL. (5) aplicar a prod. Ver bloque de verificación al final.
--   CRITERIO DE EXITO: propios secrets accesibles; cross-tenant retorna NULL;
--          0 regresión en frontend integraciones + bot outbound.
-- ============================================================

-- ── 1. pgsec_read_secret: ownership por nombre, decrypt solo si autorizado ────
CREATE OR REPLACE FUNCTION pgsec_read_secret(p_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, public, pg_catalog
AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    -- Leer SOLO el nombre (vault.secrets, sin descifrar) para el ownership check.
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN NULL;  -- no existe → no filtrar info
    END IF;

    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;  -- nombre legacy sin prefijo tenant
        END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
        ) THEN
            RETURN NULL;  -- caller no es dueño → no descifrar
        END IF;
    END IF;

    -- Autorizado (o service_role): descifrar y retornar.
    RETURN (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_id);
END;
$$;

-- ── 2. pgsec_update_secret: ownership por nombre (no-op silencioso si ajeno) ──
CREATE OR REPLACE FUNCTION pgsec_update_secret(p_id uuid, p_secret text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, public, pg_catalog
AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
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
        ) THEN
            RETURN;  -- no-op: no sobrescribir secret ajeno
        END IF;
    END IF;

    PERFORM vault.update_secret(p_id, p_secret);
END;
$$;

-- ── 3. pgsec_delete_secret: ownership por nombre (no-op silencioso si ajeno) ──
CREATE OR REPLACE FUNCTION pgsec_delete_secret(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, public, pg_catalog
AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
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
        ) THEN
            RETURN;  -- no-op: no borrar secret ajeno
        END IF;
    END IF;

    DELETE FROM vault.secrets WHERE id = p_id;
END;
$$;

-- ── 4. pgsec_upsert_secret: ownership por prefijo del nombre provisto ─────────
CREATE OR REPLACE FUNCTION pgsec_upsert_secret(
    p_name        text,
    p_secret      text,
    p_description text DEFAULT ''
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, public, pg_catalog
AS $$
DECLARE
    v_id    uuid;
    v_owner uuid;
BEGIN
    -- El caller construye el nombre; validar que el prefijo tenant sea SUYO
    -- (evita crear/sobrescribir un secret con el prefijo de otro tenant).
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;

    SELECT id INTO v_id FROM vault.secrets WHERE name = p_name LIMIT 1;
    IF v_id IS NOT NULL THEN
        PERFORM vault.update_secret(v_id, p_secret);
        RETURN v_id;
    ELSE
        RETURN vault.create_secret(p_secret, p_name, p_description);
    END IF;
END;
$$;

-- ── 5. pgsec_create_secret: ownership por prefijo del nombre provisto ─────────
CREATE OR REPLACE FUNCTION pgsec_create_secret(
    p_secret      text,
    p_name        text,
    p_description text DEFAULT ''
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, public, pg_catalog
AS $$
DECLARE
    v_owner uuid;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;

    RETURN vault.create_secret(p_secret, p_name, p_description);
END;
$$;

-- GRANTs sin cambios: el gate vive dentro de cada función (authenticated pasa
-- por la validación de ownership; service_role bypasa).
GRANT EXECUTE ON FUNCTION pgsec_read_secret(uuid)            TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_update_secret(uuid, text)    TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_delete_secret(uuid)          TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_upsert_secret(text, text, text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_create_secret(text, text, text) TO authenticated, service_role;

-- ============================================================
-- VERIFICACIÓN (correr en dev/staging tras aplicar — NO en este archivo):
--
--   -- (a) service_role lee cualquier secret (backend bot) — debe retornar valor:
--   SELECT pgsec_read_secret('<secret_id_real>');   -- como service_role → OK
--
--   -- (b) authenticated dueño lee SU secret — debe retornar valor:
--   --     (simular: SET request.jwt.claims con sub=<user_id> miembro del tenant)
--
--   -- (c) authenticated NO dueño lee secret de otro tenant — debe retornar NULL:
--   --     con JWT de user del tenant A, pgsec_read_secret('<secret_id_de_B>') → NULL
--
--   -- (d) Frontend smoke: conectar/desconectar WhatsApp, Wompi, Telegram,
--   --     Aveonline, MeLi desde /dashboard/integrations → sin error.
--
--   -- (e) Bot smoke: enviar 1 mensaje WhatsApp (backend lee access_token) → OK.
-- ============================================================
