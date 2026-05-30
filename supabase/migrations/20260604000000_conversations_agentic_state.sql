-- Rev. 109 — Agentic State Machine
-- Añade columna determinística para el estado del Inbox conversacional.
-- Estados:
--   GREETING            — primer contacto / saludo
--   EXPLORING           — cliente navega catálogo, aún no hay items
--   CART_BUILDING       — cart con ≥1 item, sin checkout iniciado
--   PII_COLLECTION      — recolección datos contacto (consent gate)
--   SHIPPING_QUOTE      — cotización de envío en curso
--   CARRIER_SELECTION   — cliente eligiendo entre opciones de envío
--   PAYMENT             — método de pago / link Wompi / COD
--   POST_PAYMENT        — orden creada, esperando confirmación o tracking
--   HUMAN_HANDOFF       — fuera del bot (asesor humano)
--
-- Importante:
--   • Esta columna es DERIVADA por el resolver del state machine,
--     no la setea el LLM. La fuente de verdad sigue siendo (cart, contact,
--     payments, orders) — esta columna es un CACHE para enrutamiento + UI Inbox.
--   • NULL = legacy (conversación pre-rev.109); el resolver la rehidrata
--     en el primer turno post-deploy.

ALTER TABLE public.conversations
    ADD COLUMN IF NOT EXISTS agentic_state TEXT;

ALTER TABLE public.conversations
    ADD CONSTRAINT conversations_agentic_state_chk
    CHECK (
        agentic_state IS NULL
        OR agentic_state IN (
            'GREETING',
            'EXPLORING',
            'CART_BUILDING',
            'PII_COLLECTION',
            'SHIPPING_QUOTE',
            'CARRIER_SELECTION',
            'PAYMENT',
            'POST_PAYMENT',
            'HUMAN_HANDOFF'
        )
    );

CREATE INDEX IF NOT EXISTS idx_conversations_agentic_state
    ON public.conversations (tenant_id, agentic_state)
    WHERE agentic_state IS NOT NULL;

COMMENT ON COLUMN public.conversations.agentic_state IS
    'Rev.109 — Estado del state machine agentic. Derivado por resolver, no por LLM.';
