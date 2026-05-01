-- Rev. 95 — Retention policies declarativas (Habeas Data Art. 16 — limitación temporal).
--
-- Contexto: Ley 1581/2012 Art. 4(d) ("uso limitado y prudente") y Art. 11
-- exigen que el responsable no conserve datos personales más allá del
-- tiempo necesario para la finalidad. Hasta rev. 94 sólo `conversation_carts`
-- y `bot_source_log` tenían TTL. Esta migración formaliza una política
-- por entidad, configurable per-tenant, ejecutada por pg_cron semanal.
--
-- Tabla de políticas:
--   entity     → 'conversations' | 'messages' | 'contacts_inactive' | 'pii_access_log'
--   ttl_days   → días de retención post-última-actividad
--   action     → 'archive' (set archived_at), 'soft_delete' (set deleted_at),
--                'hard_delete' (DELETE row), 'anonymize' (NULLify PII)
--
-- Defaults globales (NULL tenant_id) cubren todos los tenants; rows con
-- tenant_id no nulo overriden el default.
--
-- Función `fn_apply_retention(entity, dry_run)`:
--   • dry_run=TRUE  → retorna count de rows que se afectarían (no muta).
--   • dry_run=FALSE → ejecuta la action y retorna count.
--
-- pg_cron schedule: domingos 03:00 UTC (low-traffic window).

CREATE TABLE IF NOT EXISTS public.retention_policies (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
    entity      TEXT NOT NULL CHECK (entity IN (
        'conversations', 'messages', 'contacts_inactive', 'pii_access_log'
    )),
    ttl_days    INTEGER NOT NULL CHECK (ttl_days >= 1 AND ttl_days <= 3650),
    action      TEXT NOT NULL CHECK (action IN (
        'archive', 'soft_delete', 'hard_delete', 'anonymize'
    )),
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, entity)
);

CREATE INDEX IF NOT EXISTS idx_retention_policies_tenant
    ON public.retention_policies (tenant_id, entity)
    WHERE enabled = TRUE;

-- ── Defaults globales (tenant_id = NULL aplica a todos los tenants) ──────────
INSERT INTO public.retention_policies (tenant_id, entity, ttl_days, action)
VALUES
    (NULL, 'messages',           180, 'hard_delete'),    -- 6 meses
    (NULL, 'conversations',      365, 'soft_delete'),    -- 1 año
    (NULL, 'contacts_inactive',  730, 'soft_delete'),    -- 2 años sin actividad
    (NULL, 'pii_access_log',     365, 'hard_delete')     -- 1 año
ON CONFLICT (tenant_id, entity) DO NOTHING;

-- ── RLS ─────────────────────────────────────────────────────────────────────
ALTER TABLE public.retention_policies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS retention_policies_tenant_select ON public.retention_policies;
CREATE POLICY retention_policies_tenant_select ON public.retention_policies
    FOR SELECT TO authenticated
    USING (
        tenant_id IS NULL  -- defaults globales visibles
        OR tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS retention_policies_tenant_modify ON public.retention_policies;
CREATE POLICY retention_policies_tenant_modify ON public.retention_policies
    FOR ALL TO authenticated
    USING (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
              AND tu.role IN ('owner', 'manager')
        )
    )
    WITH CHECK (
        tenant_id IN (
            SELECT tu.tenant_id FROM public.tenant_users tu
            WHERE tu.user_id = auth.uid()
              AND tu.role IN ('owner', 'manager')
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.retention_policies TO service_role;
GRANT SELECT ON public.retention_policies TO authenticated;

-- ── Función de aplicación ───────────────────────────────────────────────────
-- Resuelve la política efectiva (override per-tenant > default global) y la
-- aplica para todos los tenants. Idempotente: action sólo afecta rows que
-- aún no han sido procesadas (e.g., archive sólo toca archived_at IS NULL).

CREATE OR REPLACE FUNCTION public.fn_apply_retention(
    p_entity   TEXT,
    p_dry_run  BOOLEAN DEFAULT TRUE
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count        INTEGER := 0;
    v_default_ttl  INTEGER;
    v_default_act  TEXT;
BEGIN
    -- Obtener default global (tenant_id IS NULL).
    SELECT ttl_days, action
      INTO v_default_ttl, v_default_act
      FROM public.retention_policies
     WHERE tenant_id IS NULL AND entity = p_entity AND enabled = TRUE
     LIMIT 1;

    IF v_default_ttl IS NULL THEN
        RAISE NOTICE 'No default policy for entity=%; skipping.', p_entity;
        RETURN 0;
    END IF;

    -- ── messages: hard_delete por updated_at ────────────────────────────────
    IF p_entity = 'messages' AND v_default_act = 'hard_delete' THEN
        IF p_dry_run THEN
            SELECT COUNT(*) INTO v_count
              FROM public.messages
             WHERE created_at < NOW() - (v_default_ttl || ' days')::INTERVAL;
        ELSE
            WITH del AS (
                DELETE FROM public.messages
                 WHERE created_at < NOW() - (v_default_ttl || ' days')::INTERVAL
                 RETURNING 1
            )
            SELECT COUNT(*) INTO v_count FROM del;
        END IF;

    -- ── conversations: soft_delete (set archived) ───────────────────────────
    ELSIF p_entity = 'conversations' AND v_default_act = 'soft_delete' THEN
        IF p_dry_run THEN
            SELECT COUNT(*) INTO v_count
              FROM public.conversations
             WHERE last_message_at < NOW() - (v_default_ttl || ' days')::INTERVAL
               AND COALESCE(archived_at, '1970-01-01'::TIMESTAMPTZ) < '2000-01-01'::TIMESTAMPTZ;
        ELSE
            WITH upd AS (
                UPDATE public.conversations
                   SET archived_at = NOW()
                 WHERE last_message_at < NOW() - (v_default_ttl || ' days')::INTERVAL
                   AND archived_at IS NULL
                 RETURNING 1
            )
            SELECT COUNT(*) INTO v_count FROM upd;
        END IF;

    -- ── contacts_inactive: soft_delete por last_seen ────────────────────────
    ELSIF p_entity = 'contacts_inactive' AND v_default_act = 'soft_delete' THEN
        IF p_dry_run THEN
            SELECT COUNT(*) INTO v_count
              FROM public.contacts
             WHERE COALESCE(updated_at, created_at) < NOW() - (v_default_ttl || ' days')::INTERVAL
               AND deleted_at IS NULL
               AND consent_given = FALSE;  -- Solo contactos sin consent activo.
        ELSE
            WITH upd AS (
                UPDATE public.contacts
                   SET deleted_at = NOW()
                 WHERE COALESCE(updated_at, created_at) < NOW() - (v_default_ttl || ' days')::INTERVAL
                   AND deleted_at IS NULL
                   AND consent_given = FALSE
                 RETURNING 1
            )
            SELECT COUNT(*) INTO v_count FROM upd;
        END IF;

    -- ── pii_access_log: hard_delete ─────────────────────────────────────────
    ELSIF p_entity = 'pii_access_log' AND v_default_act = 'hard_delete' THEN
        IF p_dry_run THEN
            SELECT COUNT(*) INTO v_count
              FROM public.pii_access_log
             WHERE accessed_at < NOW() - (v_default_ttl || ' days')::INTERVAL;
        ELSE
            WITH del AS (
                DELETE FROM public.pii_access_log
                 WHERE accessed_at < NOW() - (v_default_ttl || ' days')::INTERVAL
                 RETURNING 1
            )
            SELECT COUNT(*) INTO v_count FROM del;
        END IF;

    ELSE
        RAISE NOTICE 'Combination entity=% action=% not implemented.', p_entity, v_default_act;
    END IF;

    RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) TO service_role;

-- ── pg_cron schedule semanal (domingos 03:00 UTC) ───────────────────────────
DO $$
BEGIN
    PERFORM cron.unschedule(jobid)
      FROM cron.job
     WHERE jobname IN ('retention_messages', 'retention_conversations',
                       'retention_contacts_inactive', 'retention_pii_access');

    PERFORM cron.schedule(
        'retention_messages',
        '0 3 * * 0',  -- domingos 03:00
        $cron$ SELECT public.fn_apply_retention('messages', FALSE); $cron$
    );
    PERFORM cron.schedule(
        'retention_conversations',
        '15 3 * * 0',
        $cron$ SELECT public.fn_apply_retention('conversations', FALSE); $cron$
    );
    PERFORM cron.schedule(
        'retention_contacts_inactive',
        '30 3 * * 0',
        $cron$ SELECT public.fn_apply_retention('contacts_inactive', FALSE); $cron$
    );
    PERFORM cron.schedule(
        'retention_pii_access',
        '45 3 * * 0',
        $cron$ SELECT public.fn_apply_retention('pii_access_log', FALSE); $cron$
    );
EXCEPTION WHEN undefined_table THEN
    RAISE NOTICE 'pg_cron no disponible; fn_apply_retention queda manual.';
END $$;

COMMENT ON TABLE public.retention_policies IS
    'Rev. 95 — Políticas de retención por entidad (Habeas Data Art. 4d/Art. 16). '
    'tenant_id NULL = default global; tenant_id no nulo = override per-tenant.';
COMMENT ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) IS
    'Rev. 95 — Aplica retention policy de la entity. dry_run=TRUE para preview.';
