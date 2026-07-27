-- ═══════════════════════════════════════════════════════════════════════════
-- Dejar de destruir la prueba del contrato.
--
-- EN ESTE SISTEMA LA CONVERSACIÓN DE WHATSAPP ES EL CONTRATO. No hay carrito web
-- ni checkout con casillas: el cliente escribe, el bot cotiza, el cliente acepta.
-- Esa conversación es la única evidencia de qué se pactó y en qué términos.
--
-- Y se estaba borrando entera cada domingo. `retention_policies` tiene
-- ('messages', 180 días, hard_delete) habilitado, y `fn_apply_retention` borra por
-- `created_at` SIN NINGUNA GUARDA: a los seis meses desaparece la prueba de una
-- compra que legalmente hay que conservar por diez años. Mientras tanto se
-- preservan cuidadosamente `orders`, `payments` y `shipments` — o sea que se
-- conserva la evidencia contable y se destruye la contractual.
--
-- Es la única brecha del análisis legal cuyo daño es IRRECUPERABLE: todo lo demás
-- se arregla tarde; esto no.
--
-- LA NORMA, verificada el 2026-07-26 en fuente oficial
-- (alcaldiabogota.gov.co/sisjur, Ley 1480 art. 50):
--   lit. d) la aceptación "deberá ser expresa, inequívoca y verificable por la
--           autoridad competente";
--   lit. e) conservar en "mecanismos de soporte duradero" la "prueba de la relación
--           comercial, en especial de la identidad plena del consumidor, su voluntad
--           expresa de contratar", "por el mismo tiempo que se deben guardar los
--           documentos de comercio".
--
-- El plazo: DIEZ AÑOS. Cód. Comercio art. 60 y Ley 962 de 2005 art. 28, que además
-- resuelve una duda que quedaba abierta — "igual término aplicará en relación con
-- las personas, NO COMERCIANTES, que legalmente se encuentren obligadas a conservar
-- esta información". Aplica a un vendedor persona natural sea comerciante o no.
--
-- ── LO QUE ESTA MIGRACIÓN **NO** TOCA ──────────────────────────────────────
-- El borrado por solicitud de Habeas Data (`contact_cleanup.py`) queda IGUAL. Ahí
-- vive el conflicto normativo real —conservar prueba vs suprimir datos— que está
-- pendiente de concepto de abogado (ADR-0040 §6.1). Esto es otra cosa: la limpieza
-- rutinaria por antigüedad, donde nadie pidió nada y no hay conflicto que resolver.
-- Mezclarlas habría sido decidir por adelantado la pregunta que está en consulta.
-- ═══════════════════════════════════════════════════════════════════════════


-- ── 1. La aceptación, verificable ──────────────────────────────────────────

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS accepted_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS accepted_message_id     UUID,
    ADD COLUMN IF NOT EXISTS accepted_meta_message_id TEXT;

COMMENT ON COLUMN public.orders.accepted_at IS
    'Cuándo el consumidor manifestó su voluntad de contratar (Ley 1480 art. 50 lit. d). '
    'Antes solo existía como texto libre dentro de la conversación — y la conversación se '
    'borraba a los 180 días.';
COMMENT ON COLUMN public.orders.accepted_meta_message_id IS
    'El id que le asignó META a ese mensaje. Es atestación de un TERCERO: la fecha y el '
    'contenido no dependen solo de nuestra base, que es lo que la norma pide al exigir que '
    'la aceptación sea "verificable por la autoridad competente".';

CREATE INDEX IF NOT EXISTS idx_orders_sin_aceptacion
    ON public.orders (tenant_id, created_at)
    WHERE accepted_at IS NULL;


-- ── 2. Estampar la aceptación ──────────────────────────────────────────────

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
    v_orden RECORD;
    v_msg   RECORD;
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
        -- Idempotente: la aceptación es un hecho histórico y no se re-escribe.
        RETURN QUERY SELECT false, 'ya_estampada'::TEXT;
        RETURN;
    END IF;
    IF v_orden.conversation_id IS NULL THEN
        -- Pedido creado por un operador para alguien que nunca escribió: no hay
        -- manifestación del consumidor que señalar. Se dice, no se inventa una.
        RETURN QUERY SELECT false, 'sin_conversacion'::TEXT;
        RETURN;
    END IF;

    -- El último mensaje del CLIENTE en o antes de crearse el pedido. Es lo más cercano
    -- a "su voluntad expresa de contratar" que existe de forma determinística: el turno
    -- con el que cerró. No se interpreta el contenido — interpretar lenguaje natural
    -- para decidir si alguien aceptó sería justo lo que la norma no admite como
    -- verificable, y además pondría a un LLM a decidir verdad transaccional.
    SELECT m.id, m.created_at, m.meta_message_id
      INTO v_msg
      FROM public.messages m
     WHERE m.conversation_id = v_orden.conversation_id
       AND m.tenant_id = p_tenant_id
       AND m.direction = 'inbound'
       AND m.created_at <= v_orden.created_at
     ORDER BY m.created_at DESC
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'sin_mensaje_del_cliente'::TEXT;
        RETURN;
    END IF;

    UPDATE public.orders
       SET accepted_at = v_msg.created_at,
           accepted_message_id = v_msg.id,
           accepted_meta_message_id = v_msg.meta_message_id
     WHERE id = p_order_id AND tenant_id = p_tenant_id
       AND accepted_at IS NULL;

    RETURN QUERY SELECT true, NULL::TEXT;
END;
$$;

COMMENT ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) IS
    'Deja registrado cuál mensaje del cliente constituye su aceptación (Ley 1480 art. 50 '
    'lit. d). Idempotente: un hecho histórico no se re-escribe.';

REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_stamp_order_acceptance(UUID, UUID) TO service_role;


-- ── 3. La retención deja de borrar la evidencia ────────────────────────────
--
-- DOS PLAZOS, no uno. La minimización de datos (Ley 1581) y la conservación de
-- prueba (Ley 1480) apuntan en direcciones opuestas, y la forma de honrar ambas es
-- distinguir:
--   · conversación SIN pedido → 180 días. Es la mayoría del tráfico: gente que
--     preguntó y no compró. Ahí no hay relación comercial que probar.
--   · conversación CON pedido → 10 años. Ahí sí la hay.
--
-- Se preserva la conversación ENTERA del pedido, no solo el mensaje de aceptación,
-- porque no se puede saber de antemano qué turno va a importar en una disputa: el
-- precio que se prometió, el plazo de entrega que se dijo, la descripción del
-- producto. El art. 50 lit. e) habla de "la prueba de la relación comercial", que
-- es más que una línea.

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
    );
$$;

COMMENT ON FUNCTION public.es_mensaje_de_evidencia(UUID, UUID) IS
    'True si la conversación tiene al menos un pedido: entonces sus mensajes son prueba '
    'de la relación comercial (Ley 1480 art. 50 lit. e) y se conservan 10 años.';

-- Índice para que el NOT EXISTS del barrido semanal no haga seq scan de orders.
CREATE INDEX IF NOT EXISTS idx_orders_conversation_tenant
    ON public.orders (conversation_id, tenant_id)
    WHERE conversation_id IS NOT NULL;

-- El CHECK de `entity` enumera las entidades válidas, así que hay que admitir la nueva
-- antes de poder configurarla. Se extiende en vez de reemplazarse, para no perder las
-- que ya estaban.
ALTER TABLE public.retention_policies
  DROP CONSTRAINT IF EXISTS retention_policies_entity_check;
ALTER TABLE public.retention_policies
  ADD CONSTRAINT retention_policies_entity_check CHECK (entity = ANY (ARRAY[
    'conversations', 'messages', 'contacts_inactive', 'pii_access_log', 'audit_log',
    'messages_evidencia'
  ]));

-- Plazo de conservación de la PRUEBA: Cód. Comercio art. 60 / Ley 962 art. 28 → 10 años.
-- Queda como política para que sea auditable y ajustable, no escondido en el código. Si la
-- fila faltara, la función cae al mismo número: nunca se borra evidencia por falta de
-- configuración.
INSERT INTO public.retention_policies (tenant_id, entity, ttl_days, action, enabled)
VALUES (NULL, 'messages_evidencia', 3650, 'hard_delete', true)
ON CONFLICT (tenant_id, entity) DO NOTHING;


-- ── 4. La guarda, dentro del barrido ───────────────────────────────────────
--
-- Se re-crea SOLO el bloque de `messages` de `fn_apply_retention`, conservando
-- literalmente el resto de la función tal como está en producción (conversations,
-- contacts_inactive, pii_access_log). Un CREATE OR REPLACE que
-- reescribiera la función entera desde una versión vieja del repo revertiría en
-- silencio arreglos que ya están aplicados — ya pasó una vez con
-- `rpc_stock_reservation_consume`.

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

    -- Plazo de conservación de la PRUEBA de la relación comercial. Si la política no
    -- está, se usa el legal: nunca se borra evidencia por falta de configuración.
    SELECT COALESCE((
        SELECT ttl_days FROM public.retention_policies
         WHERE tenant_id IS NULL AND entity = 'messages_evidencia' AND enabled = TRUE
         LIMIT 1
    ), 3650) INTO v_ttl_evidencia;

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

        -- ── messages: DOS plazos ────────────────────────────────────────────
        -- Sin pedido → el TTL corto (minimización, Ley 1581).
        -- Con pedido → 10 años (prueba, Ley 1480 art. 50 lit. e + Cód. Comercio art. 60).
        IF p_entity = 'messages' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.messages m
                 WHERE m.tenant_id = r_tenant.tenant_id
                   AND m.created_at < NOW() - (
                        CASE WHEN public.es_mensaje_de_evidencia(m.conversation_id, m.tenant_id)
                             THEN v_ttl_evidencia ELSE v_eff_ttl END || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - (
                            CASE WHEN public.es_mensaje_de_evidencia(m.conversation_id, m.tenant_id)
                                 THEN v_ttl_evidencia ELSE v_eff_ttl END || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
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
            -- Combinación entity+action no implementada — saltar tenant.
            CONTINUE;
        END IF;

        v_total_count := v_total_count + v_count;
    END LOOP;

    RETURN v_total_count;
END;
$function$;


-- ── 5. Quién estampa, y cuándo ─────────────────────────────────────────────
--
-- POR QUÉ UN BARRIDO PROPIO Y NO COLGARLO DEL DE COMPROBANTES: el de comprobantes
-- solo mira pedidos SIN comprobante y está detrás de su propio feature flag. La
-- prueba de la aceptación no puede depender de si la emisión de comprobantes está
-- encendida — son obligaciones distintas del mismo artículo.
--
-- POR QUÉ NO UN TRIGGER: en contra entrega el pedido nace confirmado y el mensaje
-- del cliente puede llegar a `messages` en la misma transacción o justo después.
-- Diferir unos minutos hace determinístico el "último mensaje antes del pedido".

CREATE OR REPLACE FUNCTION public.rpc_find_orders_pending_acceptance(
    p_min_age_minutes INTEGER DEFAULT 5,
    p_window_days     INTEGER DEFAULT 30,
    p_limit           INTEGER DEFAULT 100
)
RETURNS TABLE (order_id UUID, tenant_id UUID)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT o.id, o.tenant_id
      FROM public.orders o
     WHERE o.accepted_at IS NULL
       AND o.conversation_id IS NOT NULL
       AND o.created_at <= NOW() - make_interval(mins => GREATEST(p_min_age_minutes, 0))
       -- La ventana evita reintentar por siempre los que nunca se van a poder estampar
       -- (un pedido viejo cuya conversación ya se borró bajo el régimen anterior).
       AND o.created_at >= NOW() - make_interval(days => GREATEST(p_window_days, 1))
     ORDER BY o.created_at
     LIMIT GREATEST(p_limit, 1);
$$;

COMMENT ON FUNCTION public.rpc_find_orders_pending_acceptance(INTEGER, INTEGER, INTEGER) IS
    'Pedidos cuya aceptación aún no quedó registrada. Lo consume el worker.';

REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_acceptance(INTEGER, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_acceptance(INTEGER, INTEGER, INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_orders_pending_acceptance(INTEGER, INTEGER, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_orders_pending_acceptance(INTEGER, INTEGER, INTEGER) TO service_role;


-- ── 6. Los pedidos que ya existen ──────────────────────────────────────────
--
-- El barrido solo alcanza los recientes. Los pedidos anteriores cuya conversación
-- sobrevivió tienen la prueba disponible AHORA y la perderían en el próximo domingo
-- si no se estampa — y una vez borrada no hay backfill posible. Se hace acá, una vez,
-- con la misma regla determinística de la función (sin interpretar contenido).

-- El LATERAL vive dentro de un CTE: Postgres no admite un LATERAL que referencie la
-- tabla que el UPDATE está modificando.
WITH aceptacion AS (
    SELECT o.id AS order_id, m.id AS msg_id, m.created_at, m.meta_message_id
      FROM public.orders o
      CROSS JOIN LATERAL (
            SELECT msg.id, msg.created_at, msg.meta_message_id
              FROM public.messages msg
             WHERE msg.conversation_id = o.conversation_id
               AND msg.tenant_id       = o.tenant_id
               AND msg.direction       = 'inbound'
               AND msg.created_at     <= o.created_at
             ORDER BY msg.created_at DESC
             LIMIT 1
           ) m
     WHERE o.accepted_at IS NULL
       AND o.conversation_id IS NOT NULL
)
UPDATE public.orders o
   SET accepted_at              = a.created_at,
       accepted_message_id      = a.msg_id,
       accepted_meta_message_id = a.meta_message_id
  FROM aceptacion a
 WHERE a.order_id = o.id;


-- ── 7. El comprobante dice a qué aceptación corresponde ────────────────────
--
-- El documento ya existía; le faltaba el vínculo con la manifestación de voluntad que lo
-- originó. Sin él, "verificable por la autoridad competente" significaba "búsquenlo en el
-- historial de WhatsApp" — el mismo historial que se estaba borrando.
--
-- El barrido de aceptación corre ANTES que el de comprobantes en cada ciclo del worker y
-- con menos diferimiento (5 min vs 10), así que todo pedido elegible para comprobante ya
-- pasó por el estampado. Aun así el campo es opcional: el snapshot es congelado y preferir
-- omitirlo a inventarlo es la única opción honesta.

-- Re-creada desde la definición VIVA en producción (verificada idéntica al harness),
-- cambiando únicamente lo necesario: reescribirla desde una versión vieja del repo
-- revertiría en silencio arreglos ya aplicados.
CREATE OR REPLACE FUNCTION public.rpc_issue_receipt(p_order_id uuid, p_tenant_id uuid)
 RETURNS TABLE(receipt_id uuid, numero text, ya_existia boolean, motivo text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_existente public.order_receipts%ROWTYPE;
    v_orden     RECORD;
    v_money     RECORD;
    v_snapshot  JSONB;
    v_seq       BIGINT;
    v_numero    TEXT;
    v_id        UUID;
BEGIN
    -- Idempotente: reemitir devuelve el mismo documento, no uno nuevo. Un
    -- reintento del webhook no puede generarle dos comprobantes al comprador.
    SELECT * INTO v_existente FROM public.order_receipts
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id;
    IF FOUND THEN
        RETURN QUERY SELECT v_existente.id, v_existente.numero, true, NULL::TEXT;
        RETURN;
    END IF;

    SELECT o.id, o.status, o.created_at, o.payment_method, o.contact_id, o.conversation_id,
           o.accepted_at, o.accepted_message_id, o.accepted_meta_message_id
      INTO v_orden
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'pedido_inexistente'::TEXT;
        RETURN;
    END IF;

    -- LA GUARDA. Si las cifras del pedido no cuadran consigo mismas, NO se emite
    -- documento. Ley 1480 art. 26: ante dos precios el consumidor solo debe el
    -- menor — documentar una contradicción es peor que no documentar (ADR-0040 §2).
    SELECT * INTO v_money FROM public.rpc_order_money(p_order_id, p_tenant_id);
    IF NOT v_money.coherente THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'cifras_incoherentes'::TEXT;
        RETURN;
    END IF;

    -- Consecutivo denso por tenant. El lock serializa solo la emisión de
    -- comprobantes del MISMO tenant, no el INSERT de pedidos.
    PERFORM pg_advisory_xact_lock(hashtext('order_receipts:' || p_tenant_id::text));
    SELECT COALESCE(MAX(numero_seq), 0) + 1 INTO v_seq
      FROM public.order_receipts WHERE tenant_id = p_tenant_id;
    v_numero := 'CP-' || LPAD(v_seq::text, 6, '0');

    v_snapshot := jsonb_build_object(
        -- v2: el documento ahora dice CUÁL manifestación del comprador lo originó.
        'version', 2,
        'emitido_at', NOW(),
        'pedido', jsonb_build_object(
            'id', v_orden.id,
            'estado', v_orden.status,
            'fecha', v_orden.created_at,
            'forma_pago', COALESCE(v_orden.payment_method, 'no_especificada')
        ),
        'vendedor', public.tenant_seller_identity(p_tenant_id),
        'comprador', (
            SELECT jsonb_strip_nulls(jsonb_build_object(
                'nombre', NULLIF(trim(c.name), ''),
                'telefono', NULLIF(trim(c.phone), ''),
                'email', NULLIF(trim(c.email), '')
            )) FROM public.contacts c WHERE c.id = v_orden.contact_id
        ),
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'titulo', oi.title,
                'cantidad', oi.quantity,
                'precio_unitario', oi.unit_price,
                'total_linea', ROUND(oi.unit_price * oi.quantity, 2)
            ) ORDER BY oi.created_at)
            FROM public.order_items oi
            WHERE oi.order_id = p_order_id AND oi.tenant_id = p_tenant_id
        ), '[]'::jsonb),
        'totales', jsonb_build_object(
            'subtotal', v_money.subtotal,
            -- El APLICADO, no el nominal: es lo que hace que las cuentas del
            -- documento cierren solas en vez de contradecirse.
            'descuento', v_money.descuento_aplicado,
            'envio', v_money.envio,
            'total', v_money.total_calculado,
            'moneda', 'COP'
        )
    );

    -- La aceptación, dentro del propio documento. Ley 1480 art. 50 lit. d) exige que sea
    -- "verificable por la autoridad competente", y un comprobante que no dice a qué
    -- manifestación del comprador corresponde obliga a ir a buscarla aparte — al historial
    -- de WhatsApp, que es justo lo que se estaba borrando. El id de Meta se incluye porque
    -- es atestación de un TERCERO: no depende de esta base.
    --
    -- Se CONCATENA en vez de armarse dentro del objeto: una clave presente con valor null
    -- insinúa que falta algo. Si el pedido no tiene aceptación registrada —creado por un
    -- operador, o anterior a este registro— la clave simplemente no existe.
    IF v_orden.accepted_at IS NOT NULL THEN
        v_snapshot := v_snapshot || jsonb_build_object(
            'aceptacion', jsonb_strip_nulls(jsonb_build_object(
                'fecha', v_orden.accepted_at,
                'mensaje_id', v_orden.accepted_message_id,
                'meta_message_id', v_orden.accepted_meta_message_id
            ))
        );
    END IF;

    INSERT INTO public.order_receipts
        (tenant_id, order_id, numero_seq, numero, snapshot, content_hash)
    VALUES
        (p_tenant_id, p_order_id, v_seq, v_numero, v_snapshot,
         encode(sha256(v_snapshot::text::bytea), 'hex'))
    RETURNING id INTO v_id;

    RETURN QUERY SELECT v_id, v_numero, false, NULL::TEXT;
END;
$function$;
