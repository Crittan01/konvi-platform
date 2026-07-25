-- W2b — Lockdown de ESCRITURA sobre las tablas de dinero/inventario. PASO 2 de 3.
--
-- Problema (verificado contra prod): las policies existentes son `FOR ALL USING
-- (tenant_id = app_current_tenant())` — distinguen TENANT pero NO ROL — y `authenticated`
-- conserva INSERT/UPDATE/DELETE. Un `operator` (empleado del Inbox) puede, por PostgREST:
--   · orders            → cambiar total_amount/discount/status (pending_payment→confirmed sin pago)
--   · order_items       → alterar unit_price/quantity de un pedido ya confirmado
--   · coupons           → crear un cupón 100% off, visible al bot
--   · coupon_redemptions→ borrar la evidencia de redención (declarada append-only, sin protección)
--   · stock_movements   → falsificar el ledger de inventario para cuadrar un faltante
--   · stock_reservations→ liberar reservas vivas (oversell) o insertar reservas fantasma
--   · tenant_subscriptions → auto-subirse el plan y otorgarse capabilities/cuotas
--   · conversation_carts → manipular el monto que se cobrará en el link de pago Wompi
-- Todo esto ELUDE la validación de transición FSM, el gate de rol, @audit_log, el step-up MFA
-- y el rate-limit, que viven únicamente en services/api (service_role).
--
-- FORMA DEL FIX — overlay RESTRICTIVE, no reescritura:
--   Las policies existentes NO se tocan (evita el riesgo de que un DROP+CREATE reconstruya algo
--   distinto de lo que hay en prod, dado el drift conocido del ledger). Se AÑADEN policies
--   `AS RESTRICTIVE`, que se combinan con AND: la permisiva sigue exigiendo el tenant, y la
--   restrictiva agrega la condición de rol. Prefijo `w2_money_` para que sean greppables y
--   revertibles con un DROP selectivo.
--
-- ALCANCE — por qué esto casi no puede romper la consola (verificado con barrido sobre apps/web):
--   El 100% de las mutaciones de pedidos, productos, variantes y cupones de la consola YA pasan
--   por services/api con service_role (que tiene BYPASSRLS). Las ÚNICAS escrituras directas con
--   sesión a estas tablas son el ajuste de inventario en catalog/page.tsx:491,499 — y ya está
--   gateado en el server action a owner/manager. Esas dos quedan explícitamente permitidas.
--
-- SELECT NO SE TOCA: no se crean policies restrictivas de lectura. Así Realtime (que evalúa
-- policies de SELECT sobre orders/conversations/messages) y todas las pantallas siguen igual.

DO $mig$
DECLARE
  t text;
  -- GRUPO A — escritura CERRADA a `authenticated`. La consola solo lee; toda mutación va por
  -- services/api con service_role. Cero escrituras directas verificadas en apps/web.
  grupo_a text[] := ARRAY[
    'orders', 'order_items', 'coupons', 'coupon_redemptions', 'products',
    'stock_reservations', 'tenant_subscriptions',
    'conversation_carts', 'conversation_cart_items'
  ];
BEGIN
  FOREACH t IN ARRAY grupo_a LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE 'w2b: tabla % no existe, se omite', t;
      CONTINUE;
    END IF;
    EXECUTE format('DROP POLICY IF EXISTS w2_money_no_insert ON public.%I', t);
    EXECUTE format('DROP POLICY IF EXISTS w2_money_no_update ON public.%I', t);
    EXECUTE format('DROP POLICY IF EXISTS w2_money_no_delete ON public.%I', t);
    EXECUTE format(
      'CREATE POLICY w2_money_no_insert ON public.%I AS RESTRICTIVE FOR INSERT TO authenticated WITH CHECK (false)', t);
    EXECUTE format(
      'CREATE POLICY w2_money_no_update ON public.%I AS RESTRICTIVE FOR UPDATE TO authenticated USING (false)', t);
    EXECUTE format(
      'CREATE POLICY w2_money_no_delete ON public.%I AS RESTRICTIVE FOR DELETE TO authenticated USING (false)', t);
  END LOOP;
  RAISE NOTICE 'w2b grupo A (escritura cerrada): % tablas', array_length(grupo_a, 1);
END $mig$;

-- ── GRUPO B — escritura permitida SOLO a owner/manager ───────────────────────
-- `product_variations`: la consola ajusta `stock_quantity` desde el catálogo
-- (catalog/page.tsx:491), ya gateado en la app a owner/manager. La policy replica ese gate en
-- la DB — que es el punto: hoy el gate vive solo en TypeScript y se elude llamando a PostgREST.
DROP POLICY IF EXISTS w2_money_no_insert ON public.product_variations;
DROP POLICY IF EXISTS w2_money_no_update ON public.product_variations;
DROP POLICY IF EXISTS w2_money_no_delete ON public.product_variations;
CREATE POLICY w2_money_no_insert ON public.product_variations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
CREATE POLICY w2_money_no_update ON public.product_variations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'));
CREATE POLICY w2_money_no_delete ON public.product_variations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.app_current_role() IN ('owner', 'manager'));

-- `stock_movements`: es un LEDGER. La consola necesita INSERT (asiento del ajuste de inventario,
-- catalog/page.tsx:499, owner/manager); UPDATE y DELETE no tienen ningún uso legítimo — poder
-- mutarlo o borrarlo es justamente lo que permite falsificar el historial para tapar un faltante.
DROP POLICY IF EXISTS w2_money_no_insert ON public.stock_movements;
DROP POLICY IF EXISTS w2_money_no_update ON public.stock_movements;
DROP POLICY IF EXISTS w2_money_no_delete ON public.stock_movements;
CREATE POLICY w2_money_no_insert ON public.stock_movements
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.app_current_role() IN ('owner', 'manager'));
CREATE POLICY w2_money_no_update ON public.stock_movements
  AS RESTRICTIVE FOR UPDATE TO authenticated USING (false);
CREATE POLICY w2_money_no_delete ON public.stock_movements
  AS RESTRICTIVE FOR DELETE TO authenticated USING (false);

COMMENT ON POLICY w2_money_no_update ON public.orders IS
  'W2b: cierra la escritura directa por PostgREST a usuarios con sesión. Toda mutación de pedidos debe ir por services/api (service_role, que bypassea RLS) donde viven la FSM, el gate de rol, @audit_log y el step-up MFA.';
