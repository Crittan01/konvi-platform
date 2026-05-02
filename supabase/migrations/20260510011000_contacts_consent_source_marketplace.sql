-- =============================================================================
-- Rev. 103 (SaaS B2B pivot) — añadir 'marketplace_meli' al CHECK de
-- contacts.consent_source.
--
-- Cuando una orden llega vía webhook MeLi creamos el contact con
-- consent_source='marketplace_meli' (no es uno de los canales operacionales
-- del operador del tenant; es el canal automatizado del marketplace).
--
-- Este source NO se ofrece en el dropdown UI — solo lo escribe el webhook.
-- =============================================================================

ALTER TABLE public.contacts
    DROP CONSTRAINT IF EXISTS contacts_consent_source_check;

ALTER TABLE public.contacts
    ADD CONSTRAINT contacts_consent_source_check
    CHECK (
        consent_source IS NULL OR
        consent_source IN (
            'manual_console',
            'whatsapp',
            'web_form',
            'phone_call',
            'in_person',
            'import',
            'other',
            'marketplace_meli'
        )
    );

COMMENT ON CONSTRAINT contacts_consent_source_check ON public.contacts IS
    'Fuentes canónicas de autorización. Rev. 103 añade ''marketplace_meli'' '
    'para contacts importados desde webhook MeLi. Solo escrito por backend.';
