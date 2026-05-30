-- =============================================================================
-- Helper UAT — restaura un contact tras prueba de STOP keyword (rev. 105 H.4.1)
--
-- Uso:
--   1. Editar la línea TARGET_PHONE abajo con el phone canónico (digits-only)
--      del contact a restaurar
--   2. Ejecutar:
--        supabase db query --linked -f scripts/uat/restore_contact_after_stop.sql
--
-- Lo que hace:
--   - Resetea consent_revoked_at + consent_revoked_reason a NULL
--   - Vuelve conversations.status='bot_active' si quedó 'opted_out'
--   - Inserta evento 'consent_re_granted' al consent_audit_log (Habeas Data
--     trail completo: revoked → re_granted)
--   - NO borra el evento 'revoked_via_stop_keyword' previo (append-only)
--
-- Idempotente: ejecutar múltiples veces no rompe (UPDATE WHERE filtra los
-- ya restaurados).
-- =============================================================================

-- Reset consent en contacts
UPDATE public.contacts
SET consent_revoked_at = NULL,
    consent_revoked_reason = NULL
WHERE phone IN ('573125835649', '+573125835649')
RETURNING id, phone, consent_revoked_at;

-- Reactivar conversación si quedó opted_out
UPDATE public.conversations
SET status = 'bot_active'
WHERE customer_phone IN ('573125835649', '+573125835649')
  AND status = 'opted_out'
RETURNING id, customer_phone, status;

-- Audit log trail: insertar evento 'granted' con evidence={trigger:'manual_uat_restore'}
-- (event canónico 'granted' por CHECK constraint; granularidad en evidence).
-- NO borra el evento 'revoked' previo (append-only).
INSERT INTO public.consent_audit_log (
    tenant_id, contact_id, phone_hash, event, source,
    actor_user_id, actor_email, evidence
)
SELECT
    c.tenant_id,
    c.id,
    encode(sha256(c.phone::bytea), 'hex'),
    'granted',
    'tenant_console',  -- source canónico (CHECK constraint)
    NULL,
    'founder@uat',
    jsonb_build_object(
        'trigger', 'manual_uat_restore',
        'reason', 'UAT cleanup post-STOP test rev105 H.4.1',
        'restored_at', NOW()::text
    )
FROM public.contacts c
WHERE c.phone IN ('573125835649', '+573125835649')
RETURNING id, contact_id, event;
