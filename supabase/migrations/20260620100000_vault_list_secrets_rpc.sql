-- Migration: vault list secrets by name pattern RPC (rev. 109)
-- Fecha: 2026-05-30
-- Branch origen: feat/remove-envia-pivot-aveonline (follow-up cleanup)
--
-- Contexto:
--   Script scripts/admin/cleanup_envia_vault_secrets.py necesita RPC para
--   listar secrets en vault.secrets por pattern de nombre (e.g. '%/envia/%').
--   Pattern reutilizable para futuros cleanups de credenciales huérfanas.
--
--   RPCs existentes (migration 20260426020000_vault_setup_and_migration.sql):
--     - pgsec_create_secret(p_secret, p_name, p_description)
--     - pgsec_read_secret(p_id) → text
--     - pgsec_update_secret(p_id, p_secret)
--     - pgsec_delete_secret(p_id)
--     - pgsec_upsert_secret
--
--   Esta migration agrega:
--     - pgsec_list_secrets_by_name_pattern(p_pattern text) → TABLE(id uuid, name text)

CREATE OR REPLACE FUNCTION pgsec_list_secrets_by_name_pattern(p_pattern text)
RETURNS TABLE (id uuid, name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
    SELECT id, name FROM vault.secrets WHERE name LIKE p_pattern;
$$;

REVOKE ALL ON FUNCTION pgsec_list_secrets_by_name_pattern(text) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION pgsec_list_secrets_by_name_pattern(text) TO service_role;
