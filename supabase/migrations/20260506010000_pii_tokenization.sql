-- Rev. 96 — Tokenización aditiva de document_number (Habeas Data — Art. 4 minimización).
--
-- Filosofía: NO migración destructiva del plaintext (R4: rompería checkout
-- Wompi que ya consume document_number en claro). Añadimos columnas
-- derivadas:
--
--   document_number_hash   → sha256 del normalizado (lookup futuro)
--   document_number_last4  → últimos 4 dígitos visibles (UX/auditoría)
--
-- Trigger las mantiene sincronizadas. Esto desbloquea:
--   • Operadores en Inbox ven sólo "...1234" en lugar del documento entero.
--   • Auditoría puede correlacionar documentos sin ver plaintext.
--   • Migración futura a Vault: cuando se decida cifrar, swap a una
--     columna `document_number_token` y migrar.
--
-- Phone: NO se cifra (R4: índice de lookup WhatsApp es path crítico).
-- Para phone se mantiene phone_hash en consent_audit_log y pii_access_log.

-- ── Columnas aditivas ───────────────────────────────────────────────────────
ALTER TABLE public.contacts
    ADD COLUMN IF NOT EXISTS document_number_hash TEXT,
    ADD COLUMN IF NOT EXISTS document_number_last4 TEXT
        CHECK (document_number_last4 IS NULL OR LENGTH(document_number_last4) <= 4);

CREATE INDEX IF NOT EXISTS idx_contacts_document_number_hash
    ON public.contacts (tenant_id, document_number_hash)
    WHERE document_number_hash IS NOT NULL;

-- ── Función de normalización + hash ─────────────────────────────────────────
-- Quita espacios, guiones, puntos. Mayúsculas. Sha256 hex.
CREATE OR REPLACE FUNCTION public.fn_document_hash(p_doc TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_doc IS NULL OR LENGTH(TRIM(p_doc)) = 0 THEN NULL
        ELSE encode(
            digest(
                upper(regexp_replace(p_doc, '[\s\-\.]', '', 'g')),
                'sha256'
            ),
            'hex'
        )
    END;
$$;

CREATE OR REPLACE FUNCTION public.fn_document_last4(p_doc TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_doc IS NULL THEN NULL
        ELSE right(regexp_replace(p_doc, '[\s\-\.]', '', 'g'), 4)
    END;
$$;

-- ── Trigger sync hash + last4 ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fn_sync_document_derived()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.document_number IS NULL THEN
        NEW.document_number_hash  := NULL;
        NEW.document_number_last4 := NULL;
    ELSE
        NEW.document_number_hash  := public.fn_document_hash(NEW.document_number);
        NEW.document_number_last4 := public.fn_document_last4(NEW.document_number);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sync_document_derived ON public.contacts;
CREATE TRIGGER trg_sync_document_derived
    BEFORE INSERT OR UPDATE OF document_number ON public.contacts
    FOR EACH ROW EXECUTE FUNCTION public.fn_sync_document_derived();

-- ── Backfill rows existentes ────────────────────────────────────────────────
UPDATE public.contacts
   SET document_number_hash  = public.fn_document_hash(document_number),
       document_number_last4 = public.fn_document_last4(document_number)
 WHERE document_number IS NOT NULL
   AND (document_number_hash IS NULL OR document_number_last4 IS NULL);

GRANT EXECUTE ON FUNCTION public.fn_document_hash(TEXT) TO service_role, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_document_last4(TEXT) TO service_role, authenticated;

COMMENT ON COLUMN public.contacts.document_number_hash IS
    'Rev. 96 — sha256 normalizado de document_number. Para lookup sin exponer plaintext.';
COMMENT ON COLUMN public.contacts.document_number_last4 IS
    'Rev. 96 — últimos 4 chars de document_number. Visible en Inbox/UI sin exponer doc completo.';
