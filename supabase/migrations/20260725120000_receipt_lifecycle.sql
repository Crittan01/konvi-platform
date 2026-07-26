-- ═══════════════════════════════════════════════════════════════════════════
-- Que el comprobante se emita y se anule SOLO.  ADR-0040 paso 4.
--
-- Hay cinco caminos por los que un pedido llega a 'confirmed' (Wompi, contra
-- entrega, dos de operador, MercadoLibre) repartidos en tres servicios. Enganchar
-- la emisión en cada uno es la receta para que mañana el sexto no la tenga — hoy
-- ya se pagó ese precio dos veces (el SLA veía 5 de ~12 escaladas; `confirm_rate`
-- no recalculaba el total).
--
-- POR QUÉ LA EMISIÓN **NO** ES UN TRIGGER
-- Sería lo natural, pero se rompe justo en el camino más frecuente: en contra
-- entrega el pedido NACE 'confirmed' en el INSERT, y sus `order_items` se
-- insertan DESPUÉS. Un trigger vería subtotal 0 contra un total > 0, concluiría
-- "cifras incoherentes" y no emitiría nunca. Lo mismo con MercadoLibre.
--
-- La emisión es entonces un BARRIDO diferido: pedidos confirmados hace más de
-- N minutos que aún no tienen comprobante. Cubre los cinco caminos y los que
-- vengan, sin depender del orden de los INSERT. Y encaja con la norma: Ley 1480
-- art. 50 lit. d) da hasta el DÍA CALENDARIO SIGUIENTE, así que unos minutos de
-- demora no es una concesión, es holgura de sobra.
--
-- LA ANULACIÓN SÍ ES UN TRIGGER: ahí no hay dependencia de orden — cuando un
-- pedido pasa a 'cancelled' ya está todo escrito. Y tiene que ser inmediato:
-- cada minuto que pasa es un comprador con un documento que afirma una compra
-- que ya no existe.
-- ═══════════════════════════════════════════════════════════════════════════


-- ── Qué falta por emitir ───────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_find_orders_pending_receipt(
    p_min_age_minutes INT DEFAULT 10,
    p_window_hours    INT DEFAULT 72,
    p_limit           INT DEFAULT 50
)
RETURNS TABLE (order_id UUID, tenant_id UUID, confirmado_hace_min INT)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT o.id, o.tenant_id,
           (EXTRACT(EPOCH FROM (NOW() - o.created_at)) / 60)::INT
    FROM public.orders o
    WHERE o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
      -- Margen para que los `order_items` ya estén escritos (ver cabecera).
      AND o.created_at <= NOW() - make_interval(mins => p_min_age_minutes)
      -- Cota inferior: no reprocesar el histórico entero en cada barrido. Un
      -- pedido más viejo que la ventana ya no se documenta automáticamente.
      AND o.created_at >= NOW() - make_interval(hours => p_window_hours)
      AND NOT EXISTS (
            SELECT 1 FROM public.order_receipts r
            WHERE r.order_id = o.id AND r.tenant_id = o.tenant_id
      )
    ORDER BY o.created_at ASC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_orders_pending_receipt(INT, INT, INT) IS
    'Pedidos confirmados que todavía no tienen comprobante. Cross-tenant por diseño '
    '(lo corre un cron sin JWT). La emisión es diferida y no un trigger porque en '
    'contra entrega el pedido nace confirmado ANTES de que existan sus order_items.';

REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_receipt(INT, INT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_receipt(INT, INT, INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_receipt(INT, INT, INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_orders_pending_receipt(INT, INT, INT) TO service_role;


-- ── Anular al cancelar ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.trg_void_receipt_on_cancel()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled' THEN
        -- Best-effort a propósito: que falle la anulación del documento NO puede
        -- impedir que se cancele el pedido. Queda el WARNING y el barrido de
        -- consistencia lo levanta después.
        BEGIN
            PERFORM public.rpc_void_receipt(NEW.id, NEW.tenant_id, 'pedido cancelado');
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING '[COMPROBANTE] no pude anular el de order=% : %', NEW.id, SQLERRM;
        END;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS orders_void_receipt_on_cancel ON public.orders;
CREATE TRIGGER orders_void_receipt_on_cancel
  AFTER UPDATE OF status ON public.orders
  FOR EACH ROW
  EXECUTE FUNCTION public.trg_void_receipt_on_cancel();

COMMENT ON FUNCTION public.trg_void_receipt_on_cancel() IS
    'Anula el comprobante cuando el pedido se cancela, venga la cancelación de donde '
    'venga. Es trigger y no barrido porque acá no hay dependencia de orden de INSERT, '
    'y porque cada minuto de demora es un comprador con un documento que ya no es cierto.';


-- ── Comprobantes que quedaron colgados ─────────────────────────────────────
-- El trigger cubre la cancelación en vivo. Esta función atrapa lo que se le
-- escape: filas escritas antes del trigger, o una anulación que falló.

CREATE OR REPLACE FUNCTION public.rpc_find_receipts_to_void(p_limit INT DEFAULT 50)
RETURNS TABLE (order_id UUID, tenant_id UUID, numero TEXT, estado_pedido TEXT)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT r.order_id, r.tenant_id, r.numero, o.status
    FROM public.order_receipts r
    JOIN public.orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    WHERE r.voided_at IS NULL AND o.status = 'cancelled'
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_receipts_to_void(INT) IS
    'Comprobantes vivos sobre pedidos cancelados: la red que atrapa lo que el trigger '
    'no cubrió (filas anteriores a él, o una anulación que falló).';

REVOKE ALL ON FUNCTION public.rpc_find_receipts_to_void(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_to_void(INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_to_void(INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_receipts_to_void(INT) TO service_role;
