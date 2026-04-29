-- =============================================================================
-- Conversation Carts — carrito conversacional persistido (WhatsApp)
-- Fecha: 2026-05-01
--
-- Reemplaza la reconstrucción del carrito vía regex sobre `messages[]` por una
-- entidad canónica con FSM explícita, items normalizados (1 fila por variante)
-- y locking optimista para tolerar concurrencia (UI + webhook Wompi).
--
-- Decisiones de diseño documentadas en .context/06-contracts.md (sección 13).
-- =============================================================================

-- ── 1. Tabla maestra del carrito ────────────────────────────────────────────
-- Un carrito está atado a una conversación viva. El `UNIQUE (conversation_id)
-- WHERE status = 'open'` garantiza que solo puede existir un carrito abierto
-- por conversación a la vez (los demás estados son terminales o de archivo).

CREATE TABLE IF NOT EXISTS public.conversation_carts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES public.contacts(id) ON DELETE SET NULL,

    -- FSM canónico del carrito.
    -- open       → cliente está agregando/modificando items
    -- checkout   → cliente confirmó intención de pago, se generó payment_link
    -- converted  → orden creada (orders.id en converted_order_id)
    -- abandoned  → TTL expiró sin checkout (alineado con PENDING_PAYMENT_TTL_MINUTES)
    -- cancelled  → cliente o agente abortó explícitamente
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'checkout', 'converted', 'abandoned', 'cancelled')),

    -- Locking optimista (ver sección "Concurrencia" en docs).
    -- Cada UPDATE debe incluir `WHERE version = :expected_version` y SET version = version + 1.
    version         INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),

    -- Datos de envío recolectados durante la conversación. JSONB porque la
    -- forma evoluciona con la conversación (ciudad → dirección → carrier).
    -- Mantener el contrato documentado, no libre.
    -- Forma esperada:
    --   {
    --     "address_line": "...",
    --     "city": "Bogotá",
    --     "dane_code": "11001000",
    --     "carrier": "envia",
    --     "rate_id": "...",
    --     "shipping_cost_cents": 12000
    --   }
    shipping_meta   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Totales calculados en cents (ver anti-pattern: nunca floats para dinero).
    -- Mantenidos por la app o por RPC; NO confiar en cálculo client-side.
    subtotal_cents  BIGINT NOT NULL DEFAULT 0 CHECK (subtotal_cents >= 0),
    shipping_cents  BIGINT NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0),
    total_cents     BIGINT NOT NULL DEFAULT 0 CHECK (total_cents >= 0),
    currency        CHAR(3) NOT NULL DEFAULT 'COP',

    -- Trazabilidad de transición a orden (cuando status='converted').
    converted_order_id UUID REFERENCES public.orders(id) ON DELETE SET NULL,

    -- TTL operativo. Un worker barre `status='open'` con last_activity_at
    -- > PENDING_PAYMENT_TTL_MINUTES y los marca `abandoned`.
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Solo un carrito 'open' por conversación.
-- Patrón: partial unique index (Postgres docs §11.9, "Partial Indexes").
-- https://www.postgresql.org/docs/current/indexes-partial.html
CREATE UNIQUE INDEX IF NOT EXISTS uniq_conversation_carts_open
    ON public.conversation_carts (conversation_id)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_conversation_carts_tenant
    ON public.conversation_carts (tenant_id);

CREATE INDEX IF NOT EXISTS idx_conversation_carts_contact
    ON public.conversation_carts (tenant_id, contact_id, status);

-- Barrido del worker para abandono por TTL.
CREATE INDEX IF NOT EXISTS idx_conversation_carts_open_ttl
    ON public.conversation_carts (last_activity_at)
    WHERE status = 'open';


-- ── 2. Items del carrito (normalizados, no JSONB array) ─────────────────────
-- Decisión: tabla relacional 1:N con UNIQUE (cart_id, variation_id).
-- Justificación documentada en sección "Estructura de items" del diseño.
-- Patrón Supabase oficial para cart/line items:
-- https://supabase.com/docs/guides/getting-started/tutorials/with-nextjs (relational)
-- Postgres normalization vs jsonb: https://www.postgresql.org/docs/current/datatype-json.html
--   "If your application demands queries against many keys, traditional table form
--    will likely outperform JSON-based representations."

CREATE TABLE IF NOT EXISTS public.conversation_cart_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    cart_id         UUID NOT NULL REFERENCES public.conversation_carts(id) ON DELETE CASCADE,

    -- Variante específica. product_id se denormaliza por velocidad de query
    -- (filtros "todos los items del producto X") pero la fuente de verdad es
    -- variation_id. Ambos NOT NULL: en e-commerce conversacional, todo item
    -- debe estar atado a una variante concreta antes de cobrar.
    product_id      UUID NOT NULL REFERENCES public.products(id) ON DELETE RESTRICT,
    variation_id    UUID NOT NULL REFERENCES public.product_variations(id) ON DELETE RESTRICT,

    quantity        INTEGER NOT NULL CHECK (quantity > 0),

    -- Snapshot de precio AL MOMENTO DE AGREGAR. Si el catálogo cambia mientras
    -- el cliente conversa, el agente decide si re-cotizar (recomputado en
    -- transición a `checkout`). Anti-pattern: no leer price desde
    -- product_variations en runtime de checkout sin congelar acá.
    unit_price_cents BIGINT NOT NULL CHECK (unit_price_cents >= 0),

    -- Metadata libre del turno que generó el item (intent, mensaje, etc.).
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Idempotencia: "1 de 10ml + 1 de 10ml" en mensajes consecutivos NO crea
    -- dos filas — el upsert RPC suma quantity sobre la fila existente.
    -- (cart_id, variation_id) es la clave natural del item.
    UNIQUE (cart_id, variation_id)
);

CREATE INDEX IF NOT EXISTS idx_cart_items_cart
    ON public.conversation_cart_items (cart_id);

CREATE INDEX IF NOT EXISTS idx_cart_items_tenant
    ON public.conversation_cart_items (tenant_id);


-- ── 3. Trigger updated_at (patrón existente del repo) ───────────────────────
-- Reusa public.touch_updated_at() definida en 20260420000005_plan_tiering_foundation.sql.
-- Si esa migración aún no se aplicó en algún entorno (no debería), la creamos
-- de forma defensiva.
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_conversation_carts_updated_at ON public.conversation_carts;
CREATE TRIGGER trg_conversation_carts_updated_at
BEFORE UPDATE ON public.conversation_carts
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_cart_items_updated_at ON public.conversation_cart_items;
CREATE TRIGGER trg_cart_items_updated_at
BEFORE UPDATE ON public.conversation_cart_items
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();


-- ── 4. RLS — multi-tenant obligatorio ───────────────────────────────────────
-- Patrón canónico del repo: policy única "Tenant Isolation" basada en
-- public.app_current_tenant() (ver 20260406181238_rls_policies.sql).
-- service_role bypassa RLS — toda query desde la API/worker DEBE filtrar por
-- tenant_id explícito (regla del repo, .context/03-rules.md).

ALTER TABLE public.conversation_carts       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_cart_items  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.conversation_carts;
CREATE POLICY "Tenant Isolation" ON public.conversation_carts
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());

DROP POLICY IF EXISTS "Tenant Isolation" ON public.conversation_cart_items;
CREATE POLICY "Tenant Isolation" ON public.conversation_cart_items
    FOR ALL USING (tenant_id = public.app_current_tenant())
    WITH CHECK (tenant_id = public.app_current_tenant());


-- ── 5. RPC: agregar/incrementar item de forma atómica e idempotente ─────────
-- Razón: la lógica "si ya existe (cart, variation) suma cantidad; si no,
-- inserta; recalcula totales; bumpea version" debe ser una sola transacción
-- para evitar race entre dos turnos del cliente o entre UI + webhook.
--
-- Patrón Postgres oficial: INSERT ... ON CONFLICT DO UPDATE
-- https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
--
-- SECURITY DEFINER + filtro explícito por p_tenant_id: cumple regla del repo
-- (service_role bypassa RLS, validar tenant en el RPC).

CREATE OR REPLACE FUNCTION public.cart_add_item(
    p_tenant_id      UUID,
    p_cart_id        UUID,
    p_product_id     UUID,
    p_variation_id   UUID,
    p_quantity       INTEGER,
    p_unit_price_cents BIGINT,
    p_expected_version INTEGER DEFAULT NULL
)
RETURNS TABLE (
    cart_id          UUID,
    new_version      INTEGER,
    subtotal_cents   BIGINT,
    total_cents      BIGINT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cart conversation_carts%ROWTYPE;
BEGIN
    IF p_quantity IS NULL OR p_quantity < 1 THEN
        RAISE EXCEPTION 'cart_add_item: quantity must be >= 1';
    END IF;

    -- Lock pesimista de la fila del carrito durante la transacción
    -- (Postgres docs §13.3.2 "Row-Level Locks").
    -- Combinado con check de version para detectar updates concurrentes.
    SELECT * INTO v_cart
    FROM public.conversation_carts
    WHERE id = p_cart_id AND tenant_id = p_tenant_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'cart_add_item: cart % not found for tenant %', p_cart_id, p_tenant_id;
    END IF;

    IF v_cart.status <> 'open' THEN
        RAISE EXCEPTION 'cart_add_item: cart % is not open (status=%)', p_cart_id, v_cart.status;
    END IF;

    IF p_expected_version IS NOT NULL AND v_cart.version <> p_expected_version THEN
        RAISE EXCEPTION 'cart_add_item: version mismatch (expected %, got %)',
            p_expected_version, v_cart.version
            USING ERRCODE = '40001'; -- serialization_failure → cliente reintenta
    END IF;

    -- Upsert idempotente: si ya hay fila para esta variante, SUMA quantity y
    -- ACTUALIZA el snapshot de precio al más reciente (decisión: el último
    -- precio cotizado durante la conversación es el que vale).
    INSERT INTO public.conversation_cart_items (
        tenant_id, cart_id, product_id, variation_id, quantity, unit_price_cents
    )
    VALUES (
        p_tenant_id, p_cart_id, p_product_id, p_variation_id, p_quantity, p_unit_price_cents
    )
    ON CONFLICT (cart_id, variation_id) DO UPDATE
    SET
        quantity = public.conversation_cart_items.quantity + EXCLUDED.quantity,
        unit_price_cents = EXCLUDED.unit_price_cents,
        updated_at = NOW();

    -- Recalcular totales desde la verdad (las filas).
    UPDATE public.conversation_carts c
    SET
        subtotal_cents = COALESCE((
            SELECT SUM(i.quantity * i.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items i
            WHERE i.cart_id = c.id
        ), 0),
        total_cents = COALESCE((
            SELECT SUM(i.quantity * i.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items i
            WHERE i.cart_id = c.id
        ), 0) + COALESCE(c.shipping_cents, 0),
        version = c.version + 1,
        last_activity_at = NOW()
    WHERE c.id = p_cart_id AND c.tenant_id = p_tenant_id
    RETURNING c.id, c.version, c.subtotal_cents, c.total_cents
    INTO cart_id, new_version, subtotal_cents, total_cents;

    RETURN NEXT;
END;
$$;


-- ── 6. Realtime (opcional, alineado con conversations/messages) ─────────────
-- El Inbox del operador puede querer ver el carrito en vivo.
ALTER PUBLICATION supabase_realtime ADD TABLE public.conversation_carts;
ALTER PUBLICATION supabase_realtime ADD TABLE public.conversation_cart_items;
ALTER TABLE public.conversation_carts      REPLICA IDENTITY FULL;
ALTER TABLE public.conversation_cart_items REPLICA IDENTITY FULL;


-- ── 7. Comentarios documentales ─────────────────────────────────────────────
COMMENT ON TABLE public.conversation_carts IS
'Carrito conversacional persistido. FSM: open → checkout → converted | abandoned | cancelled. UNIQUE parcial garantiza un carrito open por conversación. Locking optimista vía columna version.';

COMMENT ON COLUMN public.conversation_carts.version IS
'Optimistic lock counter. Toda actualización debe incluir WHERE version = :v_actual y SET version = version + 1. RPC cart_add_item lo bumpea automáticamente.';

COMMENT ON COLUMN public.conversation_carts.shipping_meta IS
'JSONB con address_line, city, dane_code, carrier, rate_id, shipping_cost_cents. La forma se documenta en .context/06-contracts.md.';

COMMENT ON TABLE public.conversation_cart_items IS
'Items del carrito. UNIQUE (cart_id, variation_id) garantiza idempotencia: agregar la misma variante dos veces SUMA quantity, no crea fila duplicada.';

COMMENT ON FUNCTION public.cart_add_item IS
'Atómico: upsert de item por (cart_id, variation_id), recálculo de subtotal/total y bump de version. Reemplaza N queries desde Python por 1 transacción.';
