-- ═══════════════════════════════════════════════════════════════════════════
-- La segunda puerta a la escritura de dinero: las RPC SECURITY DEFINER.
--
-- W2b (migración 20260725040000) cerró la escritura DIRECTA a las tablas de
-- dinero con policies RESTRICTIVE por rol. Pero una policy solo gobierna el
-- acceso a la TABLA: una función SECURITY DEFINER corre con los privilegios de
-- quien la creó y NO evalúa RLS. Con el EXECUTE otorgado a `authenticated`,
-- cualquier usuario logueado del tenant podía saltarse el candado llamando a la
-- función en vez de escribir la tabla.
--
-- El caso más claro es `cart_add_item`, cuya firma incluye
-- `p_unit_price_cents bigint`: el precio es un PARÁMETRO. Un operador podía
-- agregar ítems al carrito de un cliente al precio que quisiera — exactamente
-- lo que W2b buscaba impedir, por la puerta de al lado. Las de stock permitían
-- mover inventario sin dejar rastro en las tablas protegidas.
--
-- QUIÉN LAS USA DE VERDAD (verificado antes de revocar, no asumido):
--   • services/api            → service_role
--   • services/ai-orchestrator → service_role
--   • apps/web (navegador)    → NINGUNA. Cero referencias en todo apps/web.
-- `service_role` tiene rolbypassrls y GRANT propio, así que no se ve afectado.
--
-- FUERA DE ALCANCE a propósito: metrics_orders_summary / metrics_orders_timeseries.
-- Son agregados de solo lectura y el dashboard SÍ llama al primero. Esta
-- migración es sobre caminos de ESCRITURA de dinero.
-- ═══════════════════════════════════════════════════════════════════════════

DO $$
DECLARE
    fn RECORD;
    revocadas INT := 0;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure AS sig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prosecdef                    -- solo SECURITY DEFINER: son las que evaden RLS
          AND p.proname IN (
              'cart_add_item',
              'fn_expire_abandoned_carts',
              'rpc_stock_decrement',
              'rpc_stock_restore',
              'rpc_stock_reserve',
              'rpc_stock_reservation_consume',
              'rpc_stock_reservation_extend',
              'rpc_stock_reservation_release',
              'rpc_stock_reservation_release_by_conversation'
          )
          -- Cubre TODAS las sobrecargas: consume/extend/release tienen dos cada
          -- una, y dejar una sola abierta reabriría el hueco entero.
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn.sig);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM anon', fn.sig);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM authenticated', fn.sig);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn.sig);
        revocadas := revocadas + 1;
    END LOOP;

    RAISE NOTICE 'RPC de dinero cerradas a authenticated/anon/PUBLIC: %', revocadas;

    IF revocadas = 0 THEN
        RAISE EXCEPTION 'No se revocó ninguna función — los nombres no coinciden con el esquema. '
                        'Fallar es correcto: un NOTICE de 0 se leería como "ya estaba cerrado".';
    END IF;
END
$$;
