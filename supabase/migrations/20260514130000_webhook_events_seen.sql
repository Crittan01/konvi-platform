-- =============================================================================
-- Rev. 105 (Sem 2, F.4) — webhook_events_seen: dedup genérica universal para
-- los 5 webhooks (Wompi, MeLi, Meta, Envia, Telegram).
--
-- Contexto: existen 2 tablas específicas heredadas:
--   - wompi_events_seen (rev. 67, 20260502)
--   - meli_webhook_dedup (rev. 69, 20260430)
-- Cada una con su shape distinto y RPC propia. Patrón duplicado.
--
-- F.4 introduce tabla genérica para nuevos webhooks (Meta, Envia, Telegram),
-- mientras las dos heredadas siguen funcionando sin cambios. Migración suave:
-- handlers nuevos usan webhook_events_seen; refactor de Wompi/MeLi a la
-- genérica queda como follow-up tras estabilizar (~30d post-deploy).
--
-- Esquema unificado: (integration, event_uid, tenant_id). UNIQUE garantiza
-- que un mismo evento de un mismo provider para un mismo tenant no se
-- procese dos veces, sin colisiones cross-tenant ni cross-integration.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.webhook_events_seen (
    id            BIGSERIAL PRIMARY KEY,
    integration   TEXT NOT NULL,
        -- 'wompi' | 'meli' | 'meta' | 'envia' | 'telegram'
    event_uid     TEXT NOT NULL,
        -- ID único del evento del provider. Wompi=event.id (UUID/hash),
        -- MeLi="application_id|resource|sent", Meta=message.id,
        -- Envia=shipmentId+type+timestamp hash, Telegram=update_id.
    tenant_id     UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
        -- Nullable: algunos webhooks (Telegram /BotFather, Meta verify) no
        -- traen tenant context al momento de inserción. Resolver tenant
        -- es responsabilidad del handler antes de procesar el payload.
    event_type    TEXT,
        -- Opcional: tipo del evento ('transaction.updated', 'message',
        -- 'shipment.delivered'). Útil para filtros forensics.
    correlation_id TEXT,
        -- Opcional: trace request_id del handler que lo procesó.
    received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at  TIMESTAMPTZ,
        -- NULL si el handler aún no completó OK. UPDATE al final del flow.
    raw_signature TEXT,
        -- Opcional: hash de la firma original recibida (auditoría forensics
        -- post-incidente). NUNCA almacenar el secret plaintext.

    CONSTRAINT webhook_events_seen_integration_event_uniq
        UNIQUE (integration, event_uid)
);

-- ─── Índices ────────────────────────────────────────────────────────────────

-- Forensics: "todos los eventos de un tenant en período" (debug + auditoría).
CREATE INDEX IF NOT EXISTS webhook_events_seen_tenant_received_idx
    ON public.webhook_events_seen (tenant_id, received_at DESC)
    WHERE tenant_id IS NOT NULL;

-- Por integration para batch operations (cleanup, métricas).
CREATE INDEX IF NOT EXISTS webhook_events_seen_integration_received_idx
    ON public.webhook_events_seen (integration, received_at DESC);

-- Cleanup TTL (eventos > 30 días pueden purgarse via cron).
CREATE INDEX IF NOT EXISTS webhook_events_seen_cleanup_idx
    ON public.webhook_events_seen (received_at)
    WHERE processed_at IS NOT NULL;

-- ─── RPC atómica de dedup (patrón meli_webhook_seen extendido) ──────────────
-- INSERT ON CONFLICT que retorna TRUE si el evento ya estaba registrado
-- (=duplicado), FALSE si fue insertado por primera vez (=procesar).

CREATE OR REPLACE FUNCTION public.webhook_event_check_or_register(
    p_integration  TEXT,
    p_event_uid    TEXT,
    p_tenant_id    UUID DEFAULT NULL,
    p_event_type   TEXT DEFAULT NULL,
    p_correlation_id TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_inserted_rows INTEGER;
BEGIN
    INSERT INTO public.webhook_events_seen (
        integration, event_uid, tenant_id, event_type, correlation_id
    ) VALUES (
        p_integration, p_event_uid, p_tenant_id, p_event_type, p_correlation_id
    )
    ON CONFLICT (integration, event_uid) DO NOTHING;

    -- Si la fila NO se insertó (ROW_COUNT=0), el evento ya existía → duplicado.
    GET DIAGNOSTICS v_inserted_rows = ROW_COUNT;
    RETURN (v_inserted_rows = 0);
END;
$$;

-- Marcar como procesado (handler invoca al final del flow OK).
CREATE OR REPLACE FUNCTION public.webhook_event_mark_processed(
    p_integration TEXT,
    p_event_uid   TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    UPDATE public.webhook_events_seen
    SET processed_at = NOW()
    WHERE integration = p_integration
      AND event_uid = p_event_uid
      AND processed_at IS NULL;
    RETURN FOUND;
END;
$$;

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.webhook_events_seen ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS webhook_events_seen_tenant_select
    ON public.webhook_events_seen;
CREATE POLICY webhook_events_seen_tenant_select
    ON public.webhook_events_seen
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT/UPDATE solo via RPC SECURITY DEFINER (service_role).

-- ─── Comentarios ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.webhook_events_seen IS
    'Dedup genérica para webhooks Rev. 105 Sem 2 F.4. UNIQUE(integration, '
    'event_uid). Reemplaza gradualmente wompi_events_seen + meli_webhook_dedup '
    '(esos siguen activos durante migración 30d post-deploy).';

COMMENT ON FUNCTION public.webhook_event_check_or_register IS
    'INSERT ON CONFLICT atómico. Retorna TRUE si evento ya existía (skip), '
    'FALSE si insert OK (procesar). Patrón at-least-once safe.';

COMMENT ON FUNCTION public.webhook_event_mark_processed IS
    'Marca processed_at=NOW si el evento existe y aún no procesado. '
    'Idempotente: re-llamar con mismo evento es no-op.';
