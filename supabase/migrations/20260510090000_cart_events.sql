-- =============================================================================
-- Rev. 104 (F1-6) — cart_events: log append-only de mutaciones del cart.
--
-- Cart-as-SoT event-sourced ligero (no CQRS completo). El row materializado
-- en `conversation_carts` sigue siendo lectura optimizada, pero ahora deriva
-- del fold de los `cart_events`.
--
-- BUG-1 (city perdida) y BUG-7 (variant detector intermitente) se resuelven
-- estructuralmente: cualquier mutación queda registrada como evento explícito
-- antes de actualizar la row → el operador puede reconstruir QUÉ pasó y QUÉ
-- carrier seleccionó el cliente (audit trail conversacional).
--
-- NO toca el comportamiento actual del `cart_tool`. La emisión de eventos se
-- agrega en una capa wrapper. Migración suave: tabla nueva + RLS por tenant
-- + índices para reconstrucción cronológica.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.cart_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id         UUID NOT NULL REFERENCES public.conversation_carts(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,    -- ver constantes abajo
    event_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    triggered_by    TEXT,              -- 'bot' | 'webhook' | 'human_takeover' | 'cron' | 'system'
    correlation_id  TEXT,              -- message_id que lo provocó (cuando aplica)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Lookups frecuentes:
-- 1) "todos los eventos de un cart en orden" — reconstrucción/auditoría.
CREATE INDEX IF NOT EXISTS cart_events_cart_id_created_at_idx
    ON public.cart_events (cart_id, created_at ASC);

-- 2) "eventos recientes por tenant" — dashboard analytics.
CREATE INDEX IF NOT EXISTS cart_events_tenant_recent_idx
    ON public.cart_events (tenant_id, created_at DESC);

-- 3) "todos los eventos de un tipo en un período" — métricas (city_changed
--    spike, requires_requote rate, etc.).
CREATE INDEX IF NOT EXISTS cart_events_type_created_idx
    ON public.cart_events (event_type, created_at DESC);

-- ─── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE public.cart_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cart_events_tenant_select ON public.cart_events;
CREATE POLICY cart_events_tenant_select ON public.cart_events
    FOR SELECT
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- service_role bypasea RLS automáticamente (insert/select sin restricción).
-- Append-only: sin policy de UPDATE/DELETE para usuarios anon/authenticated.
-- (service_role puede en teoría, pero el código solo emite INSERT — F1-6 wrapper.)

COMMENT ON TABLE public.cart_events IS
    'Append-only log de mutaciones del cart. Rev. 104 F1-6. Eventos canónicos: '
    'item_added, item_proposed, item_removed, qty_changed, shipping_quoted, '
    'shipping_invalidated, carrier_selected, city_changed, consent_recorded, '
    'summary_rendered, payment_link_created, order_confirmed, coupon_applied (futuro F4).';
COMMENT ON COLUMN public.cart_events.event_type IS
    'Snake_case canónico. Lista enumerada en `services/ai-orchestrator/cart/events.py`.';
COMMENT ON COLUMN public.cart_events.triggered_by IS
    'bot | webhook | human_takeover | cron | system';
COMMENT ON COLUMN public.cart_events.correlation_id IS
    'message_id (uuid) cuando el evento responde a un inbound del cliente.';
