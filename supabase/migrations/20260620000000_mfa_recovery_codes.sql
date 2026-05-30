-- =============================================================================
-- Rev. 109 J.2.4.3 — MFA TOTP recovery codes per user
--
-- Contexto: Supabase Auth tiene MFA TOTP nativo (auth.mfa_factors), pero
-- NO genera ni valida recovery codes (códigos de respaldo one-time-use
-- para cuando el usuario pierde su authenticator).
--
-- Esta migration agrega:
--   1. Tabla mfa_recovery_codes (user_id + bcrypt hash del code).
--   2. RLS: usuario ve/borra solo SUS códigos.
--   3. RPC fn_consume_mfa_recovery_code (bcrypt check + mark used atómico).
--
-- Flow esperado:
--   • Enroll MFA TOTP via supabase.auth.mfa.enroll() — Supabase genera factor.
--   • Backend genera 8 códigos aleatorios (32 chars URL-safe), los hashea
--     bcrypt, almacena. Plaintext se muestra UNA VEZ al usuario para
--     descarga (txt). Después se descarta.
--   • Login: si TOTP code falla o usuario perdió phone, ingresa recovery
--     code. Backend invoca fn_consume_mfa_recovery_code que itera hashes
--     del user, encuentra match, marca used_at = NOW.
--   • Recovery codes son single-use: tras consume, no se pueden re-usar.
--
-- Lock-out scenario: si usuario pierde TANTO authenticator COMO recovery
-- codes, founder debe RESET via Supabase Dashboard SQL Editor (no hay UI
-- self-service — sería vector de ataque).
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.mfa_recovery_codes (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    code_hash    TEXT NOT NULL,
        -- bcrypt(plaintext). NUNCA almacenar plaintext.
    used_at      TIMESTAMPTZ,
        -- NULL = disponible. NOT NULL = consumido (no se puede reusar).
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.mfa_recovery_codes IS
    'J.2.4.3 — códigos de recuperación MFA TOTP (8 por usuario por enrollment). '
    'Bcrypt hashed. Single-use: tras consume, used_at marca momento. NUNCA '
    'almacenar plaintext.';


CREATE INDEX IF NOT EXISTS mfa_recovery_codes_user_idx
    ON public.mfa_recovery_codes (user_id, used_at);


-- RLS — usuario ve/borra solo SUS códigos. NUNCA UPDATE/INSERT direct
-- (insertions van por RPC con service_role).
ALTER TABLE public.mfa_recovery_codes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mfa_recovery_codes_owner_select
    ON public.mfa_recovery_codes;
CREATE POLICY mfa_recovery_codes_owner_select
    ON public.mfa_recovery_codes
    FOR SELECT
    TO authenticated
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS mfa_recovery_codes_owner_delete
    ON public.mfa_recovery_codes;
CREATE POLICY mfa_recovery_codes_owner_delete
    ON public.mfa_recovery_codes
    FOR DELETE
    TO authenticated
    USING (user_id = auth.uid());

-- INSERT/UPDATE: ONLY service_role (via RPC).


-- ─── RPC: consume recovery code ───────────────────────────────────────────
-- Itera códigos no-usados del user, bcrypt-compare con el plaintext recibido.
-- Si match: UPDATE used_at = NOW() y retorna TRUE.
-- Si no: retorna FALSE.

CREATE OR REPLACE FUNCTION public.fn_consume_mfa_recovery_code(
    p_user_id    UUID,
    p_code_hash  TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    matched_id BIGINT;
BEGIN
    -- IMPORTANTE: el caller (backend Python) hace bcrypt-compare del
    -- plaintext contra TODOS los hashes del user. Si encuentra match,
    -- invoca esta función con el hash matched para marcarlo used.
    -- Esto evita hacer bcrypt-compare server-side dentro de plpgsql.
    SELECT id INTO matched_id
      FROM public.mfa_recovery_codes
     WHERE user_id   = p_user_id
       AND code_hash = p_code_hash
       AND used_at IS NULL
       FOR UPDATE;

    IF matched_id IS NULL THEN
        RETURN FALSE;
    END IF;

    UPDATE public.mfa_recovery_codes
       SET used_at = NOW()
     WHERE id = matched_id;

    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION public.fn_consume_mfa_recovery_code IS
    'Marca un recovery code como usado. Atomic (FOR UPDATE lock previene '
    'doble consume). El bcrypt-compare lo hace el caller; esta función '
    'solo marca el hash matched como consumed.';

GRANT EXECUTE ON FUNCTION public.fn_consume_mfa_recovery_code TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_consume_mfa_recovery_code FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_consume_mfa_recovery_code FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_consume_mfa_recovery_code FROM anon;


-- ─── RPC: regenerar (borrar previos + crear nuevos) ───────────────────────
-- Idempotente: si el caller invoca 2x con misma lista, sobreescribe.

CREATE OR REPLACE FUNCTION public.fn_regenerate_mfa_recovery_codes(
    p_user_id     UUID,
    p_code_hashes TEXT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    inserted_count INTEGER := 0;
BEGIN
    -- Borrar codes anteriores (usados o no).
    DELETE FROM public.mfa_recovery_codes WHERE user_id = p_user_id;

    -- Insertar nuevos.
    INSERT INTO public.mfa_recovery_codes (user_id, code_hash)
    SELECT p_user_id, unnest(p_code_hashes);

    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN inserted_count;
END;
$$;

COMMENT ON FUNCTION public.fn_regenerate_mfa_recovery_codes IS
    'Regenera recovery codes del usuario: borra previos + inserta nuevos. '
    'Caller debe bcrypt-hashear los plaintexts antes de pasar el array.';

GRANT EXECUTE ON FUNCTION public.fn_regenerate_mfa_recovery_codes TO service_role;
REVOKE EXECUTE ON FUNCTION public.fn_regenerate_mfa_recovery_codes FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_regenerate_mfa_recovery_codes FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.fn_regenerate_mfa_recovery_codes FROM anon;
