-- =============================================================================
-- F4 · Decisión "Auto-registro del export CSV de auditoría (PII)".
--
-- Problema: /api/audit/export saca hasta 5000 eventos con PII (emails, payloads)
-- y NO dejaba huella. Escribir el registro desde el route de Next con el cliente
-- del usuario es inválido: pii_access_log tiene INSERT revocado a `authenticated`
-- (solo service_role) y es append-only. El write debe ejecutarse con privilegios
-- de definer, no con los del cliente user.
--
-- Solución: RPC SECURITY DEFINER `log_audit_export(...)` — equivalente a nivel DB
-- del endpoint backend recomendado. Deriva tenant + actor del JWT (no spoofable),
-- y registra el acceso en:
--   • pii_access_log (purpose='data_export')  → traza de acceso a PII (Art. 9).
--   • audit_log      (action='exported')      → evento en el registro de cambios.
-- Cada insert va en su propio sub-bloque best-effort: un fallo (p.ej. contact_id
-- aún NOT NULL si 20260704150001 no está aplicada) no aborta el otro ni rompe la
-- descarga (el route la invoca con try/catch, nunca bloquea el CSV).
--
-- Idempotente (CREATE OR REPLACE + GRANT). NO aplicar automáticamente.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.log_audit_export(
    p_row_count   INTEGER,
    p_filters     JSONB   DEFAULT '{}'::jsonb,
    p_ip          TEXT    DEFAULT NULL,
    p_user_agent  TEXT    DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_tenant  UUID := app_current_tenant();
    v_uid     UUID := auth.uid();
    v_email   TEXT := auth.jwt() ->> 'email';
BEGIN
    -- Sin tenant resoluble no hay contexto seguro: no-op (evita filas huérfanas).
    IF v_tenant IS NULL THEN
        RETURN;
    END IF;

    -- ── Traza de acceso a PII (compliance Habeas Data Art. 9) ────────────────
    BEGIN
        INSERT INTO public.pii_access_log (
            tenant_id, contact_id, accessed_by, actor_user_id,
            purpose, fields_accessed, ip_address, user_agent
        ) VALUES (
            v_tenant,
            NULL,                                    -- export masivo: no ligado a 1 contacto
            'user:' || COALESCE(v_email, v_uid::text, 'unknown'),
            v_uid,
            'data_export',
            ARRAY['audit_events']::text[],
            p_ip,
            p_user_agent
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'log_audit_export: pii_access_log insert skipped (%).', SQLERRM;
    END;

    -- ── Evento en el registro de cambios (self-audit del export) ─────────────
    BEGIN
        INSERT INTO public.audit_log (
            tenant_id, user_id, user_email, action, entity_type, entity_id, payload
        ) VALUES (
            v_tenant,
            v_uid,
            v_email,
            'exported',
            'audit_log',
            NULL,
            jsonb_build_object('row_count', p_row_count, 'filters', COALESCE(p_filters, '{}'::jsonb))
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'log_audit_export: audit_log insert skipped (%).', SQLERRM;
    END;
END;
$$;

REVOKE ALL ON FUNCTION public.log_audit_export(INTEGER, JSONB, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.log_audit_export(INTEGER, JSONB, TEXT, TEXT) TO authenticated;

COMMENT ON FUNCTION public.log_audit_export(INTEGER, JSONB, TEXT, TEXT) IS
    'F4 — Registra un export CSV de auditoría en pii_access_log (data_export) + '
    'audit_log (exported). SECURITY DEFINER: deriva tenant/actor del JWT. Best-effort.';
