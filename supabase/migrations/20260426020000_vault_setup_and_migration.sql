-- Vault: RPC wrappers + migración de credenciales a Supabase Vault
-- Requiere: pgsodium habilitado (extensión ya activada en el proyecto)
-- Referencia: https://supabase.com/docs/guides/database/vault

-- ── 1. RPC wrappers (callable desde Python/TypeScript via supabase.rpc) ───────
-- SECURITY DEFINER + search_path fijo para acceder a vault schema de forma segura.

CREATE OR REPLACE FUNCTION pgsec_create_secret(
    p_secret      text,
    p_name        text,
    p_description text DEFAULT ''
)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
    SELECT vault.create_secret(p_secret, p_name, p_description);
$$;

CREATE OR REPLACE FUNCTION pgsec_read_secret(p_id uuid)
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
    SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_id;
$$;

CREATE OR REPLACE FUNCTION pgsec_update_secret(p_id uuid, p_secret text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
BEGIN
    PERFORM vault.update_secret(p_id, p_secret);
END;
$$;

CREATE OR REPLACE FUNCTION pgsec_delete_secret(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
BEGIN
    DELETE FROM vault.secrets WHERE id = p_id;
END;
$$;

GRANT EXECUTE ON FUNCTION pgsec_create_secret TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_read_secret   TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_update_secret TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION pgsec_delete_secret TO authenticated, service_role;

-- ── 2. Migración de datos existentes a Vault ──────────────────────────────────
-- Por cada credencial en texto plano, la mueve a Vault y guarda el UUID.
-- Idempotente: omite filas que ya tienen *_secret_id.

DO $$
DECLARE
    r      record;
    v_id   uuid;
    v_cred jsonb;
BEGIN

    -- ── Envia: api_token ──────────────────────────────────────────────────────
    FOR r IN
        SELECT id, tenant_id, credentials
        FROM public.tenant_integrations
        WHERE provider = 'envia'
          AND credentials ? 'api_token'
          AND NOT (credentials ? 'api_token_secret_id')
    LOOP
        IF (r.credentials->>'api_token') IS NOT NULL
           AND (r.credentials->>'api_token') <> '' THEN
            v_id := vault.create_secret(
                r.credentials->>'api_token',
                r.tenant_id::text || '/envia/api_token',
                'Envia API token'
            );
            UPDATE public.tenant_integrations
            SET credentials = (r.credentials - 'api_token')
                              || jsonb_build_object('api_token_secret_id', v_id::text)
            WHERE id = r.id;
            RAISE NOTICE 'Envia api_token migrado → tenant %', r.tenant_id;
        END IF;
    END LOOP;

    -- ── WhatsApp: access_token ────────────────────────────────────────────────
    FOR r IN
        SELECT id, tenant_id, credentials
        FROM public.tenant_integrations
        WHERE provider = 'whatsapp'
          AND credentials ? 'access_token'
          AND NOT (credentials ? 'access_token_secret_id')
    LOOP
        IF (r.credentials->>'access_token') IS NOT NULL
           AND (r.credentials->>'access_token') <> '' THEN
            v_id := vault.create_secret(
                r.credentials->>'access_token',
                r.tenant_id::text || '/whatsapp/access_token',
                'WhatsApp access token'
            );
            UPDATE public.tenant_integrations
            SET credentials = (r.credentials - 'access_token')
                              || jsonb_build_object('access_token_secret_id', v_id::text)
            WHERE id = r.id;
            RAISE NOTICE 'WhatsApp access_token migrado → tenant %', r.tenant_id;
        END IF;
    END LOOP;

    -- ── MeLi: access_token + refresh_token ───────────────────────────────────
    FOR r IN
        SELECT id, tenant_id, credentials
        FROM public.tenant_integrations
        WHERE provider = 'mercadolibre'
          AND (credentials ? 'access_token' OR credentials ? 'refresh_token')
    LOOP
        v_cred := r.credentials;

        IF (v_cred->>'access_token') IS NOT NULL
           AND NOT (v_cred ? 'access_token_secret_id') THEN
            v_id := vault.create_secret(
                v_cred->>'access_token',
                r.tenant_id::text || '/meli/access_token',
                'MeLi access token'
            );
            v_cred := (v_cred - 'access_token')
                      || jsonb_build_object('access_token_secret_id', v_id::text);
        END IF;

        IF (v_cred->>'refresh_token') IS NOT NULL
           AND NOT (v_cred ? 'refresh_token_secret_id') THEN
            v_id := vault.create_secret(
                v_cred->>'refresh_token',
                r.tenant_id::text || '/meli/refresh_token',
                'MeLi refresh token'
            );
            v_cred := (v_cred - 'refresh_token')
                      || jsonb_build_object('refresh_token_secret_id', v_id::text);
        END IF;

        IF v_cred IS DISTINCT FROM r.credentials THEN
            UPDATE public.tenant_integrations
            SET credentials = v_cred
            WHERE id = r.id;
            RAISE NOTICE 'MeLi tokens migrados → tenant %', r.tenant_id;
        END IF;
    END LOOP;

    -- ── Telegram: bot_token ───────────────────────────────────────────────────
    FOR r IN
        SELECT id, tenant_id, config
        FROM public.notification_settings
        WHERE channel = 'telegram'
          AND config ? 'bot_token'
          AND NOT (config ? 'bot_token_secret_id')
    LOOP
        IF (r.config->>'bot_token') IS NOT NULL
           AND (r.config->>'bot_token') <> '' THEN
            v_id := vault.create_secret(
                r.config->>'bot_token',
                r.tenant_id::text || '/telegram/bot_token',
                'Telegram bot token'
            );
            UPDATE public.notification_settings
            SET config = (r.config - 'bot_token')
                         || jsonb_build_object('bot_token_secret_id', v_id::text)
            WHERE id = r.id;
            RAISE NOTICE 'Telegram bot_token migrado → tenant %', r.tenant_id;
        END IF;
    END LOOP;

    RAISE NOTICE '✅ Migración Vault completada';
END;
$$;
