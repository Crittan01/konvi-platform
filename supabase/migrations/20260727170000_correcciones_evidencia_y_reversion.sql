-- ═══════════════════════════════════════════════════════════════════════════
-- Correcciones a lo desplegado ayer, salidas de una auditoría adversarial
-- (85 agentes, 27 candidatos, 24 sobrevivieron a tres refutadores) más el
-- recorrido E2E contra producción. Cada bloque cita el escenario que lo motiva.
-- ═══════════════════════════════════════════════════════════════════════════


-- ── 1. La retención dejaba de aplicarse ENTERA, en silencio ────────────────
--
-- EL DEFECTO, medido contra producción:
-- El `CASE WHEN es_mensaje_de_evidencia(...)` dentro del intervalo hizo que el umbral
-- dependiera de la fila. El predicado dejó de ser sargable: donde antes había
-- `Index Only Scan ... (tenant_id = X AND created_at < now() - '180 days')` —que toca
-- solo la cola vencida— quedó un `Bitmap Index Scan (tenant_id = X)` con todo lo demás
-- en `Filter`, leyendo del heap TODOS los mensajes del tenant, incluidos los de ayer.
--
-- Y la función NO se puede inlinear: tiene `SET search_path`, así que `proconfig` no es
-- NULL y `inline_function()` la descarta siempre. Medido en prod con 200.000 iteraciones:
-- EXISTS inline 119 ms vs. vía la función 2.230 ms — 19x, ~10,5 µs por fila.
--
-- Con `statement_timeout = 120000` (fijo en la configuración del servidor, sin override
-- para el rol del cron) y UN solo presupuesto para el bucle de TODOS los tenants —los
-- statements internos de plpgsql no reinician el timer—, al crecer la tabla el barrido
-- del domingo aborta, pg_cron revierte la transacción y **no se borra nada de nadie**:
-- ni la evidencia (correcto) ni la minimización de 180 días (incumplimiento de Ley 1581).
-- El fallo solo queda en `cron.job_run_details`, que nadie lee: un grep del repo entero
-- da cero referencias. Y no se recupera solo — cada domingo la tabla es más grande.
--
-- EL ARREGLO: dos DELETE sargables en vez de uno con CASE.
--   · El primero borra lo vencido a TTL corto que NO es evidencia. `created_at <` es un
--     predicado normal otra vez, así que el índice acota el barrido a la cola.
--   · El segundo borra lo vencido a TTL largo, sin importar qué sea.
-- El EXISTS va INLINE (no por la función) para que el planner pueda convertirlo en
-- anti-join en vez de llamarlo por fila.

-- ── 2. Un carrito abandonado no es una relación comercial ──────────────────
--
-- `es_mensaje_de_evidencia` devolvía true ante CUALQUIER fila en `orders`. Pero el flujo
-- normal del bot inserta la orden en `pending_payment` al pedir el link, y si el cliente
-- no paga, a los 35 minutos el worker la pasa a `cancelled` y la fila se queda ahí para
-- siempre. Resultado: quien pidió un link y no pagó veía TODA su conversación retenida
-- 3650 días en vez de 180.
--
-- Es sobre-retención de datos personales 20x por encima de la política declarada, contra
-- el principio de minimización (Ley 1581 art. 4 lit. d y art. 11) — justo el eje que la
-- migración de ayer decía estar equilibrando. Y no es hipotético: de los 3 pedidos que
-- hay hoy en producción, 2 están en `cancelled`.
--
-- CRITERIO NUEVO — hubo relación comercial si el pedido llegó a comprometer algo:
--   · alcanzó un estado de ejecución (confirmed / processing / shipped / delivered), o
--   · tiene un pago aprobado, o
--   · se le emitió un comprobante.
-- Un `pending`/`pending_payment` abandonado, y un `cancelled` que nunca pasó de ahí, NO.
-- Un pedido CANCELADO que sí llegó a confirmarse o a pagarse SÍ cuenta: ahí hubo
-- contrato, y es exactamente el caso que termina en disputa.

CREATE OR REPLACE FUNCTION public.es_mensaje_de_evidencia(
    p_conversation_id UUID,
    p_tenant_id       UUID
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.orders o
         WHERE o.conversation_id = p_conversation_id
           AND o.tenant_id = p_tenant_id
           AND (
                o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
             OR EXISTS (SELECT 1 FROM public.payments p
                         WHERE p.order_id = o.id AND p.status = 'approved')
             OR EXISTS (SELECT 1 FROM public.order_receipts r
                         WHERE r.order_id = o.id)
           )
    );
$$;

COMMENT ON FUNCTION public.es_mensaje_de_evidencia(UUID, UUID) IS
    'True si la conversación sostiene una relación comercial REAL: un pedido que llegó a '
    'ejecutarse, que se pagó, o que produjo comprobante. Un carrito abandonado en '
    'pending_payment y luego cancelado NO cuenta — retenerlo 10 años sería sobre-retención '
    'contra Ley 1581 art. 4 lit. d).';

-- Índice que sostiene el anti-join del barrido. El de ayer
-- (idx_orders_conversation_tenant) sirve para el EXISTS, pero solo si el planner llega a
-- él; con el criterio nuevo hay que poder descartar rápido los pedidos que no cuentan.
CREATE INDEX IF NOT EXISTS idx_orders_evidencia
    ON public.orders (conversation_id, tenant_id)
    WHERE conversation_id IS NOT NULL
      AND status IN ('confirmed', 'processing', 'shipped', 'delivered');


CREATE OR REPLACE FUNCTION public.fn_apply_retention(p_entity text, p_dry_run boolean DEFAULT true)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_total_count   INTEGER := 0;
    v_count         INTEGER;
    v_default_ttl   INTEGER;
    v_default_act   TEXT;
    v_eff_ttl       INTEGER;
    v_eff_act       TEXT;
    v_ttl_evidencia INTEGER;
    r_tenant        RECORD;
BEGIN
    SELECT ttl_days, action
      INTO v_default_ttl, v_default_act
      FROM public.retention_policies
     WHERE tenant_id IS NULL AND entity = p_entity AND enabled = TRUE
     LIMIT 1;

    IF v_default_ttl IS NULL THEN
        RAISE NOTICE 'No default policy for entity=%; skipping.', p_entity;
        RETURN 0;
    END IF;

    -- Plazo de conservación de la PRUEBA. Si la política no está, se usa el legal: nunca
    -- se borra evidencia por falta de configuración.
    SELECT COALESCE((
        SELECT ttl_days FROM public.retention_policies
         WHERE tenant_id IS NULL AND entity = 'messages_evidencia' AND enabled = TRUE
         LIMIT 1
    ), 3653) INTO v_ttl_evidencia;

    FOR r_tenant IN
        SELECT id AS tenant_id FROM public.tenants
    LOOP
        SELECT ttl_days, action
          INTO v_eff_ttl, v_eff_act
          FROM public.retention_policies
         WHERE tenant_id = r_tenant.tenant_id
           AND entity = p_entity
           AND enabled = TRUE
         LIMIT 1;

        IF v_eff_ttl IS NULL THEN
            v_eff_ttl := v_default_ttl;
            v_eff_act := v_default_act;
        END IF;

        v_count := 0;

        -- ── messages: DOS pasadas SARGABLES, no un CASE por fila ────────────
        IF p_entity = 'messages' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.messages m
                 WHERE m.tenant_id = r_tenant.tenant_id
                   AND (
                        m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     OR (m.created_at < NOW() - make_interval(days => v_eff_ttl)
                         AND NOT EXISTS (
                             SELECT 1 FROM public.orders o
                              WHERE o.conversation_id = m.conversation_id
                                AND o.tenant_id = m.tenant_id
                                AND (o.status IN ('confirmed','processing','shipped','delivered')
                                  OR EXISTS (SELECT 1 FROM public.payments p
                                              WHERE p.order_id = o.id AND p.status = 'approved')
                                  OR EXISTS (SELECT 1 FROM public.order_receipts r
                                              WHERE r.order_id = o.id))))
                   );
            ELSE
                -- Pasada A: lo vencido a TTL corto que NO sostiene relación comercial.
                -- El EXISTS va inline para que el planner pueda hacer anti-join en vez de
                -- llamar a una función no inlineable una vez por fila.
                WITH del AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_eff_ttl)
                       AND NOT EXISTS (
                           SELECT 1 FROM public.orders o
                            WHERE o.conversation_id = m.conversation_id
                              AND o.tenant_id = m.tenant_id
                              AND (o.status IN ('confirmed','processing','shipped','delivered')
                                OR EXISTS (SELECT 1 FROM public.payments p
                                            WHERE p.order_id = o.id AND p.status = 'approved')
                                OR EXISTS (SELECT 1 FROM public.order_receipts r
                                            WHERE r.order_id = o.id)))
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;

                -- Pasada B: lo vencido al plazo legal de conservación, sea lo que sea.
                -- Un mensaje sin conversación (`conversation_id IS NULL`) cae acá y no en
                -- la pasada A: el NOT EXISTS con NULL no lo alcanzaría, así que sin esta
                -- pasada viviría para siempre.
                WITH del2 AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     RETURNING 1
                )
                SELECT v_count + COUNT(*) INTO v_count FROM del2;
            END IF;

        -- ── conversations: soft_delete (set archived_at) ────────────────────
        ELSIF p_entity = 'conversations' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.conversations
                 WHERE tenant_id = r_tenant.tenant_id
                   AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND archived_at IS NULL;
            ELSE
                WITH upd AS (
                    UPDATE public.conversations
                       SET archived_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND archived_at IS NULL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── contacts_inactive: soft_delete por updated_at sin consent ───────
        ELSIF p_entity = 'contacts_inactive' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.contacts
                 WHERE tenant_id = r_tenant.tenant_id
                   AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND deleted_at IS NULL
                   AND consent_given = FALSE;
            ELSE
                WITH upd AS (
                    UPDATE public.contacts
                       SET deleted_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND deleted_at IS NULL
                       AND consent_given = FALSE
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── pii_access_log: hard_delete ─────────────────────────────────────
        ELSIF p_entity = 'pii_access_log' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.pii_access_log
                 WHERE tenant_id = r_tenant.tenant_id
                   AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.pii_access_log
                     WHERE tenant_id = r_tenant.tenant_id
                       AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
            END IF;

        ELSE
            CONTINUE;
        END IF;

        v_total_count := v_total_count + v_count;
    END LOOP;

    RETURN v_total_count;
END;
$function$;

-- El GRANT sigue siendo solo backend: el CREATE OR REPLACE conserva los privilegios, y
-- los de esta función se cerraron en 20260727150000. Se re-afirma por si alguien la
-- re-crea desde una versión vieja del repo.
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM anon;
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) TO service_role;


-- ── 3. Diez años son 3653 días, no 3650 ────────────────────────────────────
--
-- Tres días de menos. El CHECK, además, topaba en 3650, así que el valor correcto no se
-- podía ni configurar: la prueba se borraba tres días antes de que venciera el término
-- del art. 60 del Cód. Comercio. Se sube el techo a 3660 para dejar margen a los años
-- bisiestos sin abrir la puerta a retenciones arbitrarias.

ALTER TABLE public.retention_policies
  DROP CONSTRAINT IF EXISTS retention_policies_ttl_days_check;
ALTER TABLE public.retention_policies
  ADD CONSTRAINT retention_policies_ttl_days_check
  CHECK (ttl_days >= 1 AND ttl_days <= 3660);

UPDATE public.retention_policies
   SET ttl_days = 3653
 WHERE entity = 'messages_evidencia' AND ttl_days = 3650;


-- ── 4. La aceptación apuntaba al mensaje equivocado ────────────────────────
--
-- LA REGLA ESTABA INVERTIDA. Se tomaba el ÚLTIMO mensaje del cliente anterior al pedido.
-- Pero entre el "sí" y el INSERT pasan segundos reales —la ventana de coalescencia (5 s),
-- el poll (hasta 3 s), el turno del LLM y varias llamadas HTTP— y cualquier cosa que el
-- cliente escriba en ese hueco gana el ORDER BY:
--
--     09:59:30  bot     "¿confirmas?"
--     10:00:00  cliente "sí confirmo"          ← ESTO es la aceptación
--     10:00:12  cliente "¿y llega mañana?"     ← esto ganaba
--     10:00:20  se crea el pedido
--
-- Quedaba registrada una pregunta de logística como manifestación de voluntad, y se
-- congelaba así en el comprobante, que es inmutable.
--
-- LA REGLA CORRECTA: el PRIMER mensaje del cliente después de la última respuesta del bot
-- anterior al pedido. Es el turno sobre el que el bot actuó, y es el mismo criterio que
-- arregla el segundo escenario sin ninguna lógica extra:
--
--     10:00:01  cliente "Confirmo la compra"   ← primero del turno: correcto
--     10:00:04  cliente "gracias!!"            ← se coalescieron; este ganaba antes
--
-- En un turno coalescido el worker combina los fragmentos SOLO en memoria y despacha el
-- último, así que el contenido almacenado del que ganaba era "gracias!!" — o, si el último
-- fragmento era un sticker o un audio, texto vacío. Con la regla nueva gana el primero,
-- que es donde está la manifestación.
--
-- DOS GUARDAS MÁS:
--   · Proximidad. Una aceptación y su pedido están a segundos, no a horas. Un candidato
--     muy anterior no originó esa compra.
--   · Un mensaje prueba UN pedido. Antes, dos pedidos en la misma conversación sin mensaje
--     nuevo en medio heredaban el mismo `accepted_message_id`: dos contratos distintos
--     probados con la misma frase.
--
-- RESIDUO CONOCIDO Y DECLARADO: un pedido que el operador crea desde la consola DENTRO de
-- una conversación (el router acepta `conversation_id`) puede seguir tomando un mensaje
-- que no es una aceptación. Por eso se marca `accepted_source`: quien lea el registro
-- sabe si es una aceptación resuelta en el turno o una inferida por cercanía.

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS accepted_source TEXT;

COMMENT ON COLUMN public.orders.accepted_source IS
    '"inferida" = la dedujo el barrido de respaldo por posición en el turno. Se registra '
    'para que nadie lea el campo como si fuera una manifestación capturada en vivo.';

CREATE OR REPLACE FUNCTION public.rpc_stamp_order_acceptance(
    p_order_id  UUID,
    p_tenant_id UUID
)
RETURNS TABLE (estampado BOOLEAN, motivo TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_orden      RECORD;
    v_msg        RECORD;
    v_ultimo_bot TIMESTAMPTZ;
BEGIN
    SELECT o.id, o.conversation_id, o.created_at, o.accepted_at
      INTO v_orden
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'pedido_inexistente'::TEXT;
        RETURN;
    END IF;
    IF v_orden.accepted_at IS NOT NULL THEN
        RETURN QUERY SELECT false, 'ya_estampada'::TEXT;
        RETURN;
    END IF;
    IF v_orden.conversation_id IS NULL THEN
        RETURN QUERY SELECT false, 'sin_conversacion'::TEXT;
        RETURN;
    END IF;

    -- La última respuesta del bot anterior al pedido abre el turno vigente. Lo que el
    -- cliente escribió DESPUÉS de esa respuesta y ANTES del pedido es ese turno.
    SELECT MAX(m.created_at) INTO v_ultimo_bot
      FROM public.messages m
     WHERE m.conversation_id = v_orden.conversation_id
       AND m.tenant_id = p_tenant_id
       AND m.direction = 'outbound'
       AND m.created_at < v_orden.created_at;

    SELECT m.id, m.created_at, m.meta_message_id
      INTO v_msg
      FROM public.messages m
     WHERE m.conversation_id = v_orden.conversation_id
       AND m.tenant_id = p_tenant_id
       AND m.direction = 'inbound'
       AND m.created_at <= v_orden.created_at
       -- Del turno vigente. Sin respuesta previa del bot (el cliente abrió y compró de
       -- una), no hay turno anterior que excluir.
       AND (v_ultimo_bot IS NULL OR m.created_at > v_ultimo_bot)
       -- Proximidad: una aceptación y su pedido están a segundos, no a horas.
       AND m.created_at >= v_orden.created_at - INTERVAL '30 minutes'
       -- Un mensaje prueba UN pedido.
       AND NOT EXISTS (
           SELECT 1 FROM public.orders o2
            WHERE o2.tenant_id = p_tenant_id
              AND o2.accepted_message_id = m.id
              AND o2.id <> p_order_id
       )
     -- ASCENDENTE: el PRIMERO del turno, que es donde está la manifestación.
     ORDER BY m.created_at ASC
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'sin_mensaje_del_cliente'::TEXT;
        RETURN;
    END IF;

    UPDATE public.orders
       SET accepted_at = v_msg.created_at,
           accepted_message_id = v_msg.id,
           accepted_meta_message_id = v_msg.meta_message_id,
           accepted_source = 'inferida'
     WHERE id = p_order_id AND tenant_id = p_tenant_id
       AND accepted_at IS NULL;

    RETURN QUERY SELECT true, NULL::TEXT;
END;
$$;

COMMENT ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) IS
    'Registra el PRIMER mensaje del cliente en el turno sobre el que el bot actuó — no el '
    'último, que puede ser algo que llegó mientras se armaba el pedido. Nunca reutiliza un '
    'mensaje que ya prueba otro pedido.';

REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) TO service_role;

-- Un mensaje prueba UN pedido, y que sea imposible violarlo no depende de que la RPC lo
-- recuerde: dos caminos concurrentes chocarían contra el índice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_accepted_message
    ON public.orders (tenant_id, accepted_message_id)
    WHERE accepted_message_id IS NOT NULL;


-- ── 5. Dos reclamos sobre el mismo pedido no pueden reversar el doble ──────
--
-- El UNIQUE era por `claim_id`, y `claims` no limita a un reclamo por pedido. La guarda
-- de valor comparaba contra el total del pedido de forma individual, sin sumar lo ya
-- radicado. Un pedido de $200.000 con dos reclamos ("no me llegó" y "llegó defectuoso")
-- producía dos constancias válidas por $200.000 cada una.
--
-- Eso es precisamente el material que el art. 2.2.2.51.8 le da al emisor para oponer "la
-- inexistencia de la operación" y tumbar el trámite entero — el riesgo que la propia
-- migración decía querer evitar.

CREATE OR REPLACE FUNCTION public.rpc_registrar_reversion(
    p_claim_id        UUID,
    p_tenant_id       UUID,
    p_causal          TEXT,
    p_razones         TEXT,
    p_valor           NUMERIC,
    p_instrumento     TEXT    DEFAULT NULL,
    p_es_parcial      BOOLEAN DEFAULT FALSE,
    p_items           JSONB   DEFAULT NULL,
    p_bien_a_disposicion BOOLEAN DEFAULT FALSE,
    p_canal           TEXT    DEFAULT 'whatsapp',
    p_conversation_id UUID    DEFAULT NULL,
    p_message_id      UUID    DEFAULT NULL,
    p_meta_message_id TEXT    DEFAULT NULL
)
RETURNS TABLE (id UUID, radicado TEXT, ya_existia BOOLEAN, motivo TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_claim      RECORD;
    v_existente  RECORD;
    v_procede    TEXT;
    v_radicado   TEXT;
    v_constancia JSONB;
    v_id         UUID;
    v_total      NUMERIC;
    v_ya_radicado NUMERIC;
BEGIN
    SELECT c.id, c.order_id, c.ticket_number, c.customer_id
      INTO v_claim
      FROM public.claims c
     WHERE c.id = p_claim_id AND c.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'reclamo_inexistente'::TEXT;
        RETURN;
    END IF;
    IF v_claim.order_id IS NULL THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'reclamo_sin_pedido'::TEXT;
        RETURN;
    END IF;

    SELECT r.id, r.radicado INTO v_existente
      FROM public.payment_reversal_requests r
     WHERE r.claim_id = p_claim_id AND r.tenant_id = p_tenant_id;
    IF FOUND THEN
        RETURN QUERY SELECT v_existente.id, v_existente.radicado, true, NULL::TEXT;
        RETURN;
    END IF;

    v_procede := public.reversion_procede(v_claim.order_id, p_tenant_id);
    IF v_procede <> 'procede' THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, v_procede;
        RETURN;
    END IF;

    SELECT o.total_amount INTO v_total
      FROM public.orders o WHERE o.id = v_claim.order_id AND o.tenant_id = p_tenant_id;

    -- Lo ya radicado sobre ESTE pedido, por cualquier otro reclamo. `FOR UPDATE` no sirve
    -- sobre un agregado: se serializa por el pedido para que dos radicaciones simultáneas
    -- no lean ambas el mismo total previo.
    PERFORM pg_advisory_xact_lock(hashtextextended(v_claim.order_id::text, 0));

    SELECT COALESCE(SUM(r.valor), 0) INTO v_ya_radicado
      FROM public.payment_reversal_requests r
     WHERE r.order_id = v_claim.order_id
       AND r.tenant_id = p_tenant_id
       AND r.estado <> 'desistida';

    IF v_total IS NOT NULL AND (v_ya_radicado + p_valor) > v_total THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'valor_excede_el_pedido'::TEXT;
        RETURN;
    END IF;

    v_radicado := 'RV-' || LPAD(COALESCE(v_claim.ticket_number, 0)::text, 6, '0');

    INSERT INTO public.payment_reversal_requests (
        tenant_id, claim_id, order_id, radicado, causal, razones, valor,
        es_parcial, items_json, instrumento, canal, bien_a_disposicion,
        conversation_id, message_id, meta_message_id
    ) VALUES (
        p_tenant_id, p_claim_id, v_claim.order_id, v_radicado, p_causal, p_razones,
        p_valor, p_es_parcial, p_items, p_instrumento, p_canal, p_bien_a_disposicion,
        p_conversation_id, p_message_id, p_meta_message_id
    ) RETURNING payment_reversal_requests.id INTO v_id;

    v_constancia := jsonb_build_object(
        'version', 1,
        'radicado', v_radicado,
        'presentada_at', NOW(),
        'presentada_co', to_char(NOW() AT TIME ZONE 'America/Bogota',
                                 'DD/MM/YYYY HH24:MI') || ' (hora Colombia)',
        'causal', p_causal,
        'razones', p_razones,
        'valor', p_valor,
        'es_parcial', p_es_parcial,
        'moneda', 'COP',
        'canal', p_canal,
        'instrumento', p_instrumento,
        'bien_a_disposicion', p_bien_a_disposicion,
        -- La identificación de la operación la exige el art. 2.2.2.51.7 num. 4 como
        -- contenido de la notificación al emisor: número, fecha y hora. El comprador no
        -- puede armarla si nosotros no se la damos.
        'operacion', (
            SELECT jsonb_strip_nulls(jsonb_build_object(
                'pedido', o.id,
                'fecha', o.created_at,
                'fecha_co', to_char(o.created_at AT TIME ZONE 'America/Bogota',
                                    'DD/MM/YYYY HH24:MI') || ' (hora Colombia)',
                'total', o.total_amount,
                'referencia_pago', (SELECT pm.wompi_link_id FROM public.payments pm
                                     WHERE pm.order_id = o.id ORDER BY pm.created_at DESC LIMIT 1)
            )) FROM public.orders o WHERE o.id = v_claim.order_id
        ),
        'pedido', jsonb_build_object('id', v_claim.order_id, 'reclamo', v_claim.ticket_number),
        'vendedor', public.tenant_seller_identity(p_tenant_id),
        'fundamento', 'Ley 1480 de 2011 art. 51; Decreto 1074 de 2015 art. 2.2.2.51.4'
    );

    UPDATE public.payment_reversal_requests
       SET constancia = v_constancia,
           constancia_hash = encode(sha256(v_constancia::text::bytea), 'hex'),
           constancia_emitida_at = NOW()
     WHERE payment_reversal_requests.id = v_id;

    RETURN QUERY SELECT v_id, v_radicado, false, NULL::TEXT;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_registrar_reversion(
    UUID, UUID, TEXT, TEXT, NUMERIC, TEXT, BOOLEAN, JSONB, BOOLEAN, TEXT, UUID, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_registrar_reversion(
    UUID, UUID, TEXT, TEXT, NUMERIC, TEXT, BOOLEAN, JSONB, BOOLEAN, TEXT, UUID, UUID, TEXT
) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_registrar_reversion(
    UUID, UUID, TEXT, TEXT, NUMERIC, TEXT, BOOLEAN, JSONB, BOOLEAN, TEXT, UUID, UUID, TEXT
) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_registrar_reversion(
    UUID, UUID, TEXT, TEXT, NUMERIC, TEXT, BOOLEAN, JSONB, BOOLEAN, TEXT, UUID, UUID, TEXT
) TO service_role;


-- ── 6. La constancia dejaba de entregarse y el barrido giraba para siempre ─
--
-- El buscador no calculaba la ventana de servicio de 24 h de Meta, a diferencia de su
-- hermano el acuse del comprobante. Escenario real y previsto por la norma —el art.
-- 2.2.2.51.4 dice "cualquiera fuere el medio"—: la queja entra por teléfono, el operador
-- la radica desde la consola con el `conversation_id` de WhatsApp, y el último mensaje
-- entrante del comprador fue hace tres días. Meta rechaza el free-form (131047),
-- `send_whatsapp_message` devuelve None sin lanzar, el worker loguea "se reintenta" y no
-- marca nada: 288 POST fallidos por día, para siempre, sin métrica ni alerta. Y peor, el
-- `ORDER BY ... LIMIT 50` deja esas filas envenenadas a la cabeza de la cola, tapando las
-- constancias nuevas que sí eran entregables.

CREATE OR REPLACE FUNCTION public.rpc_find_constancias_por_entregar(
    p_csw_hours INTEGER DEFAULT 24,
    p_limit     INTEGER DEFAULT 50
)
RETURNS TABLE (
    reversal_id UUID, tenant_id UUID, conversation_id UUID,
    radicado TEXT, constancia JSONB, dentro_de_csw BOOLEAN
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT r.id, r.tenant_id, r.conversation_id, r.radicado, r.constancia,
           EXISTS (
               SELECT 1 FROM public.messages m
                WHERE m.conversation_id = r.conversation_id
                  AND m.tenant_id = r.tenant_id
                  AND m.direction = 'inbound'
                  AND m.created_at >= NOW() - make_interval(hours => p_csw_hours)
           )
      FROM public.payment_reversal_requests r
     WHERE r.constancia_emitida_at IS NOT NULL
       AND r.constancia_entregada_at IS NULL
       AND r.constancia_entrega_fallida IS NULL
       AND r.conversation_id IS NOT NULL
     ORDER BY r.constancia_emitida_at
     LIMIT GREATEST(p_limit, 1);
$$;

REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER, INTEGER) TO service_role;

-- La firma vieja de un solo argumento queda huérfana: se elimina para que nadie la llame
-- por accidente y crea que verificó la ventana.
DROP FUNCTION IF EXISTS public.rpc_find_constancias_por_entregar(INTEGER);


-- ── 7. Una constancia sin conversación era invisible para siempre ──────────
--
-- El buscador exige `conversation_id IS NOT NULL`, así que una queja radicada por
-- teléfono o correo sobre un comprador sin conversación de WhatsApp no se entregaba
-- nunca, y tampoco se marcaba como fallida: nadie se enteraba de que faltaba entregarla.
-- Se marcan de una vez, con motivo, para que el operador las vea y las mande por otro
-- medio — que es lo que la norma permite.

UPDATE public.payment_reversal_requests
   SET constancia_entrega_fallida = 'sin_conversacion_whatsapp'
 WHERE constancia_emitida_at IS NOT NULL
   AND constancia_entregada_at IS NULL
   AND constancia_entrega_fallida IS NULL
   AND conversation_id IS NULL;
