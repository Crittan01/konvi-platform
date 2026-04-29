-- =============================================================================
-- Fix RPC cart_add_item — desambiguar nombres de OUT params.
--
-- Bug en 20260501000000_conversation_carts.sql: los OUT params se llamaban
-- `cart_id`, `subtotal_cents`, `total_cents` (idénticos a columnas de
-- `conversation_cart_items` y `conversation_carts`). Postgres no podía
-- resolver la referencia dentro del UPDATE ... RETURNING.
--
-- Solución: prefijo `out_` en los nombres de OUT params para garantizar
-- unicidad. El esquema de retorno cambia ligeramente pero el repo Python
-- ya consume `result["new_version"]` etc, no por posición.
-- =============================================================================

DROP FUNCTION IF EXISTS public.cart_add_item(uuid, uuid, uuid, uuid, integer, bigint, integer);

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
    out_cart_id        UUID,
    out_new_version    INTEGER,
    out_subtotal_cents BIGINT,
    out_total_cents    BIGINT
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
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO public.conversation_cart_items AS i (
        tenant_id, cart_id, product_id, variation_id, quantity, unit_price_cents
    )
    VALUES (
        p_tenant_id, p_cart_id, p_product_id, p_variation_id, p_quantity, p_unit_price_cents
    )
    ON CONFLICT (cart_id, variation_id) DO UPDATE
    SET
        quantity = i.quantity + EXCLUDED.quantity,
        unit_price_cents = EXCLUDED.unit_price_cents,
        updated_at = NOW();

    UPDATE public.conversation_carts c
    SET
        subtotal_cents = COALESCE((
            SELECT SUM(it.quantity * it.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items it
            WHERE it.cart_id = c.id
        ), 0),
        total_cents = COALESCE((
            SELECT SUM(it.quantity * it.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items it
            WHERE it.cart_id = c.id
        ), 0) + COALESCE(c.shipping_cents, 0),
        version = c.version + 1,
        last_activity_at = NOW()
    WHERE c.id = p_cart_id AND c.tenant_id = p_tenant_id
    RETURNING c.id, c.version, c.subtotal_cents, c.total_cents
    INTO out_cart_id, out_new_version, out_subtotal_cents, out_total_cents;

    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.cart_add_item IS
'Atómico: upsert (cart_id, variation_id), recálculo de totales y bump de version. OUT params con prefijo out_ para evitar ambigüedad con columnas de tablas.';
