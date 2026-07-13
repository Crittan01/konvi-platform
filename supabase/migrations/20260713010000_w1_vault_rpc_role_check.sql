-- ============================================================
-- W1 (auditoría 2026-07-13) — HIGH: Vault RPCs autorizan por MEMBRESÍA, no por rol
-- ============================================================
-- Los 5 pgsec_* (read/update/delete/upsert/create) chequeaban SOLO membresía:
--     NOT EXISTS (SELECT 1 FROM tenant_users WHERE tenant_id=v_owner AND user_id=auth.uid())
-- → cualquier miembro autenticado (incluido OPERATOR) podía, vía PostgREST RPC directo,
--   DESCIFRAR los secrets del tenant: access_token de WhatsApp, bot_token de Telegram,
--   refresh_token de MeLi, private/events key de Wompi. El redirect de la página de
--   integraciones es UI, no seguridad — el gate real es el RPC.
--
-- FIX: añadir `AND role IN ('owner','manager')` al check de membresía en los 5 RPCs.
-- Coincide con el modelo real (la página integrations redirige a operator; owner/manager
-- leen/escriben). service_role (backend bot/connector) BYPASA (auth.uid() NULL) → intacto.
-- Se reproduce cada función 1:1 de 20260624000000, solo con el rol añadido.

-- ── 1. pgsec_read_secret ──────────────────────────────────────────────────────
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
$$;

-- ── 2. pgsec_update_secret ────────────────────────────────────────────────────
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
              AND role IN ('owner', 'manager')
        ) THEN
            RETURN;
        END IF;
    END IF;
    PERFORM vault.update_secret(p_id, p_secret);
END;
$$;

-- ── 3. pgsec_delete_secret ────────────────────────────────────────────────────
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
              AND role IN ('owner', 'manager')
        ) THEN
            RETURN;
        END IF;
    END IF;
    DELETE FROM vault.secrets WHERE id = p_id;
END;
$$;

-- ── 4. pgsec_upsert_secret ────────────────────────────────────────────────────
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
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
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

-- ── 5. pgsec_create_secret ────────────────────────────────────────────────────
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
              AND role IN ('owner', 'manager')
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;
    RETURN vault.create_secret(p_secret, p_name, p_description);
END;
$$;

-- GRANTs sin cambios (el gate de rol vive dentro de cada función; service_role bypasa).
GRANT EXECUTE ON FUNCTION pgsec_read_secret(uuid)              TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_update_secret(uuid, text)      TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_delete_secret(uuid)            TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_upsert_secret(text, text, text)   TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_create_secret(text, text, text)   TO authenticated, service_role;
