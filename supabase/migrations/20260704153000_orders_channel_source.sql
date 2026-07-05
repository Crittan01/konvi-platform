-- Migración F3: identidad estable de canal en `orders` (source + external_order_id).
--
-- Contexto: hoy los pedidos de Mercado Libre se correlacionan por prefijo de
-- notas (`notes LIKE 'MeLi order #…%'`). Si el operador edita las notas, el
-- webhook pierde o duplica la orden (afecta status, decremento de stock y
-- tracking). Estas columnas dan una identidad de canal estable e inmune a edición.
--
-- Degradación segura: el código (services/api/routers/meli_webhook.py) hace
-- feature-detect (`_orders_channel_cols_available`) y cae al match por notes si
-- estas columnas aún no existen. Por eso es seguro desplegar código ANTES de la
-- migración (expand-contract).
--
-- INTERVENCION HUMANA REQUERIDA: aplicar en ventana de mantenimiento verificando
-- drift del ledger (feedback_supabase_migrations). Idempotente.

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS external_order_id TEXT;

COMMENT ON COLUMN public.orders.source IS
    'Canal de origen del pedido: NULL = nativo (bot/manual), ''mercadolibre'' = MeLi. Base para futuros marketplaces.';
COMMENT ON COLUMN public.orders.external_order_id IS
    'ID del pedido en el sistema externo (ej. order_id de Mercado Libre). Identidad estable del canal.';

-- Unicidad por (tenant, source, external_order_id): evita duplicar un pedido MeLi
-- reentrante en el webhook. Índice PARCIAL: solo aplica cuando ambos están
-- presentes, de modo que los pedidos nativos (source/external NULL) no se ven
-- afectados y pueden coexistir sin restricción.
CREATE UNIQUE INDEX IF NOT EXISTS orders_tenant_source_external_uq
    ON public.orders (tenant_id, source, external_order_id)
    WHERE source IS NOT NULL AND external_order_id IS NOT NULL;

-- Índice de lookup para el webhook (búsqueda por external_order_id dentro del tenant).
CREATE INDEX IF NOT EXISTS orders_tenant_external_order_idx
    ON public.orders (tenant_id, external_order_id)
    WHERE external_order_id IS NOT NULL;
