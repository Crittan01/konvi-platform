-- Vault helper: create-or-update por nombre.
-- Resuelve el error 23505 cuando se reconecta una integración sin haber desconectado primero.
-- La restricción UNIQUE en vault.secrets.name se gestiona internamente.

CREATE OR REPLACE FUNCTION pgsec_upsert_secret(
    p_name        text,
    p_secret      text,
    p_description text DEFAULT ''
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vault, pg_catalog
AS $$
DECLARE
    v_id uuid;
BEGIN
    -- Buscar secreto existente por nombre
    SELECT id INTO v_id FROM vault.secrets WHERE name = p_name LIMIT 1;

    IF v_id IS NOT NULL THEN
        -- Ya existe → actualizar valor
        PERFORM vault.update_secret(v_id, p_secret);
        RETURN v_id;
    ELSE
        -- No existe → crear nuevo
        RETURN vault.create_secret(p_secret, p_name, p_description);
    END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION pgsec_upsert_secret TO authenticated, service_role;
