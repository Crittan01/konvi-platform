-- =============================================================================
-- Rev. 105 (Sem 4, H.2.2 Fase A) — envia_webhook_capture_log: tabla
-- TEMPORAL para descubrimiento empírico de payloads de webhooks Envia.
--
-- DOSSIER REF: envia-dossier-2026-05-05.md sec. 4 L.7 + L.7b
--   "schemas no documentados, descubrir empíricamente con Test Webhook"
--   POST /ship/webhooktest/ permite enviar sample payload al webhook URL.
--
-- USO: durante Fase A de H.2.2, capturamos los 5 tipos de webhook Envia
-- (onShipmentStatusUpdate, statusUpdateWithEcommerceInfo, simpleTracking,
-- ecommerceTracking, surcharge) en su FORMA REAL antes de codear procesadores.
-- Decidir Fase B con data real, no suposiciones.
--
-- VIDA ÚTIL: temporal — esta tabla se DROPea o renombra cuando Fase B
-- implemente procesadores reales basados en los schemas descubiertos.
-- Migration de drop quedará en un revision posterior tras documentar
-- payloads en dossier.
--
-- DECISIÓN ARQUITECTÓNICA: append-only máxima, sin RLS estricto en INSERT
-- (service_role escribe, no usuarios), SELECT con tenant scope para
-- forensics si hay disputa con Envia.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.envia_webhook_capture_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
        -- nullable: posible que llegue webhook con secret válido pero
        -- tenant_id no resoluble en URL — capturamos igual para forensics.
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    secret_match    BOOLEAN NOT NULL,
        -- TRUE si secret-token URL coincide con F.10 webhook_secrets activo
        -- o grace_period. FALSE si rechazado (igual capturamos para detectar
        -- ataques o mal-config).
    headers_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- request.headers completos. CRÍTICO: descubrir si Envia incluye
        -- algún header tipo X-Envia-Event-Type, X-Envia-Signature
        -- (aunque dossier L.3 dice no hay HMAC, validamos empíricamente).
    query_params    JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- request.query_params (por si Envia agrega params).
    raw_body        TEXT,
        -- raw body como string. Captura todo incluso si NO es JSON parseable.
    parsed_body     JSONB,
        -- intento de json.loads(raw_body). NULL si parseo falló.
    inferred_type   TEXT,
        -- intento de derivar tipo del body o headers. NULL si no se puede.
        -- Valores esperados (basado en panel Envia):
        --   'onShipmentStatusUpdate' | 'statusUpdateWithEcommerceInfo' |
        --   'simpleTracking' | 'ecommerceTracking' | 'surcharge' | NULL
    source_ip       INET,
        -- IP del cliente Envia (para validación L.5 / V.5 IPs allowlist).
    notes           TEXT
        -- anotación humana opcional al revisar la captura.
);

-- ─── Índices ────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS envia_webhook_capture_log_tenant_received_idx
    ON public.envia_webhook_capture_log (tenant_id, received_at DESC)
    WHERE tenant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS envia_webhook_capture_log_inferred_type_idx
    ON public.envia_webhook_capture_log (inferred_type, received_at DESC)
    WHERE inferred_type IS NOT NULL;

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.envia_webhook_capture_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS envia_webhook_capture_log_tenant_select
    ON public.envia_webhook_capture_log;
CREATE POLICY envia_webhook_capture_log_tenant_select
    ON public.envia_webhook_capture_log
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- INSERT solo via service_role (endpoint webhook usa service_role).

-- ─── Comentario ─────────────────────────────────────────────────────────────

COMMENT ON TABLE public.envia_webhook_capture_log IS
    'Append-only capture de payloads webhooks Envia para descubrimiento '
    'empírico de schemas (Rev. 105 Sem 4 H.2.2 Fase A). Dossier ref: '
    'envia-dossier-2026-05-05.md sec. 4 L.7 + L.7b. TEMPORAL: drop o '
    'rename tras Fase B cuando los schemas estén documentados.';
