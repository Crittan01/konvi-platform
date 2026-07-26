-- ═══════════════════════════════════════════════════════════════════════════
-- La verdad del dinero de un pedido, en un solo lugar.
--
-- POR QUÉ EN SQL Y NO EN UN HELPER DE PYTHON
-- Hay cinco caminos por los que un pedido llega a 'confirmed' (Wompi, contra
-- entrega, dos de operador, MercadoLibre) y viven en tres servicios distintos.
-- Un helper hay que acordarse de llamarlo desde cada uno, y hoy mismo se vio dos
-- veces qué pasa cuando una convención la cumplen solo algunas rutas: el SLA
-- ignoraba 7 de ~12 escaladas, y `confirm_rate` actualizaba el envío sin
-- recalcular el total. Una función que lee del esquema no se puede "olvidar" de
-- cumplirse.
--
-- QUÉ RESUELVE
-- Un comprobante de compra es un compromiso público sobre cifras. Ley 1480
-- art. 26: si al consumidor le aparecen dos precios distintos, solo está obligado
-- al menor. Antes de emitir cualquier documento hay que poder responder
-- "¿las cifras de este pedido cuadran entre sí?" — y hasta ahora nadie podía.
--
-- EL DESCUENTO APLICADO vs EL NOMINAL
-- `orders.total_amount` se calcula con un clamp: max(0, subtotal + envío −
-- descuento). Cuando el descuento supera a ítems+envío, el clamp dispara y el
-- pedido queda diciendo, por ejemplo:
--     Subtotal 50.000 · Descuento −80.000 · Envío 10.000 · TOTAL 0
-- que no es aritmética, es una contradicción impresa. Por eso se devuelven las
-- DOS cifras: `descuento_nominal` (lo que dice la columna) y `descuento_aplicado`
-- (lo que de verdad se descontó, tope = subtotal + envío). Imprimiendo el
-- aplicado las cuentas cierran solas y el documento deja de contradecirse.
--
-- Es SECURITY INVOKER a propósito: RLS decide qué pedidos ve quien pregunta.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.rpc_order_money(
    p_order_id  UUID,
    p_tenant_id UUID
)
RETURNS TABLE (
    subtotal            NUMERIC,
    descuento_nominal   NUMERIC,
    descuento_aplicado  NUMERIC,
    envio               NUMERIC,
    total_calculado     NUMERIC,
    total_registrado    NUMERIC,
    coherente           BOOLEAN,
    diferencia          NUMERIC
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    WITH o AS (
        SELECT ord.id,
               COALESCE(ord.shipping_cost, 0)   AS envio,
               COALESCE(ord.discount_amount, 0) AS descuento,
               COALESCE(ord.total_amount, 0)    AS total
        FROM public.orders ord
        WHERE ord.id = p_order_id AND ord.tenant_id = p_tenant_id
    ),
    items AS (
        SELECT COALESCE(SUM(oi.unit_price * oi.quantity), 0) AS subtotal
        FROM public.order_items oi
        WHERE oi.order_id = p_order_id AND oi.tenant_id = p_tenant_id
    ),
    calc AS (
        SELECT i.subtotal,
               o.descuento AS descuento_nominal,
               -- Tope real: no se puede descontar más de lo que hay que pagar.
               LEAST(o.descuento, i.subtotal + o.envio) AS descuento_aplicado,
               o.envio,
               o.total AS total_registrado
        FROM o CROSS JOIN items i
    )
    SELECT ROUND(c.subtotal, 2),
           ROUND(c.descuento_nominal, 2),
           ROUND(c.descuento_aplicado, 2),
           ROUND(c.envio, 2),
           ROUND(c.subtotal + c.envio - c.descuento_aplicado, 2),
           ROUND(c.total_registrado, 2),
           -- Tolerancia de UN CENTAVO. Los totales son numeric(10,2) pero se
           -- construyen en float en Python, y el peso colombiano no circula en
           -- centavos: un centavo es ruido de redondeo, no un error de dinero.
           -- Un error real es de miles (el de #175 era de 8.000). Un peso entero
           -- sí se marca: ahí la aritmética ya no cierra.
           ABS((c.subtotal + c.envio - c.descuento_aplicado) - c.total_registrado) <= 0.01,
           ROUND((c.subtotal + c.envio - c.descuento_aplicado) - c.total_registrado, 2)
    FROM calc c;
$$;

COMMENT ON FUNCTION public.rpc_order_money(UUID, UUID) IS
    'Cifras de un pedido calculadas desde la fuente de verdad (order_items) y si '
    'cuadran con orders.total_amount. `descuento_aplicado` es el efectivo (tope '
    'subtotal+envío); imprimir ése y no el nominal es lo que evita un documento que '
    'se contradice. Guarda previa a emitir cualquier comprobante (Ley 1480 art. 26).';

REVOKE ALL ON FUNCTION public.rpc_order_money(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_order_money(UUID, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.rpc_order_money(UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_order_money(UUID, UUID) TO service_role;


-- ── Barrido: pedidos confirmados cuyas cifras NO cuadran ────────────────────
-- Sin esto, la incoherencia solo se descubre cuando alguien mira un pedido
-- concreto. `confirm_rate` la producía en silencio hasta hoy.

CREATE OR REPLACE FUNCTION public.rpc_find_incoherent_orders(
    p_window_hours INT DEFAULT 48,
    p_limit        INT DEFAULT 50
)
RETURNS TABLE (
    order_id         UUID,
    tenant_id        UUID,
    status           TEXT,
    total_registrado NUMERIC,
    total_calculado  NUMERIC,
    diferencia       NUMERIC
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT o.id, o.tenant_id, o.status, m.total_registrado, m.total_calculado, m.diferencia
    FROM public.orders o
    CROSS JOIN LATERAL public.rpc_order_money(o.id, o.tenant_id) m
    WHERE o.status NOT IN ('cancelled', 'pending')
      AND o.created_at >= NOW() - make_interval(hours => p_window_hours)
      AND NOT m.coherente
    ORDER BY ABS(m.diferencia) DESC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_incoherent_orders(INT, INT) IS
    'Pedidos recientes cuyas cifras no cuadran consigo mismas. Cross-tenant por '
    'diseño (lo corre un cron sin JWT) — de ahí que solo service_role la ejecute.';

REVOKE ALL ON FUNCTION public.rpc_find_incoherent_orders(INT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_incoherent_orders(INT, INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_incoherent_orders(INT, INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_incoherent_orders(INT, INT) TO service_role;
