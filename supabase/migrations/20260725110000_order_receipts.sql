-- ═══════════════════════════════════════════════════════════════════════════
-- El comprobante de compra: armado y congelado.  ADR-0040, paso 3.
--
-- Ley 1480 art. 50 lit. d) obliga a remitir acuse de recibo del pedido a más
-- tardar el día calendario siguiente, y a poner a disposición un resumen
-- imprimible o descargable. El lit. a) exige que el vendedor esté identificado.
--
-- POR QUÉ TODO ESTO VIVE EN SQL Y NO EN PYTHON
-- `services/api` y `services/ai-orchestrator` NO pueden importarse entre sí
-- (rootDir separados en Render), y hay cinco caminos por los que un pedido llega
-- a 'confirmed' repartidos entre ambos. Un armador en Python habría que
-- duplicarlo — y hoy ya se pagó dos veces el precio de una lógica que solo
-- cumplen algunas rutas (el SLA ignoraba 7 de ~12 escaladas; `confirm_rate` no
-- recalculaba el total). Acá el documento se arma igual venga de donde venga.
--
-- CONGELAR ES LO QUE CONVIERTE EL DOCUMENTO EN COMPROBANTE
-- `order_items` ya congela `title` y `unit_price` y sobrevive al borrado del
-- catálogo. Pero el VENDEDOR se resolvería con un lookup vivo, y un comprobante
-- no puede cambiar de contenido porque el tenant editó su perfil el mes
-- siguiente. Por eso el snapshot guarda el estado del mundo en el instante de
-- la emisión, y el `content_hash` permite demostrar después que no se tocó.
--
-- EL CONSECUTIVO VA EN EL COMPROBANTE, NO EN `orders`
-- `payment_link_tool.py` y `cart_tool.py` CANCELAN la orden pending_payment y
-- crean otra cada vez que el cliente cambia el carrito o aplica un cupón.
-- Numerar en el INSERT de `orders` haría que un cliente indeciso queme 3-4
-- números en pedidos que nunca existieron comercialmente, y metería un lock por
-- tenant en el INSERT de dinero de mayor concurrencia del sistema. Numerando lo
-- EMITIDO, el consecutivo queda denso y ese camino no se toca.
-- ═══════════════════════════════════════════════════════════════════════════


-- ── 1. Quién es el vendedor, dicho de una sola manera ───────────────────────
--
-- Los campos legales (#163) están HOY vacíos en todos los tenants: la migración
-- solo llenó `doc_numero` desde el `nit` legado. Así que la degradación no es un
-- borde teórico, es el camino que se recorre el primer día. Cada campo cae a su
-- mejor alternativa y, si no hay ninguna, queda NULL para que el renderizador
-- omita la línea entera — un "Documento: —" es peor que no tener la línea.

CREATE OR REPLACE FUNCTION public.tenant_seller_identity(p_tenant_id UUID)
RETURNS JSONB
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    WITH t AS (
        SELECT
            -- NULLIF(trim(...)) trata '', '   ' y NULL como lo mismo: ausencia.
            -- Un campo con espacios pasa cualquier chequeo de NULL y después
            -- imprime una línea vacía.
            NULLIF(trim(tn.razon_social), '')            AS razon_social,
            NULLIF(trim(tn.name), '')                    AS nombre_comercial,
            NULLIF(trim(tn.doc_tipo), '')                AS doc_tipo,
            COALESCE(NULLIF(trim(tn.doc_numero), ''),
                     NULLIF(trim(tn.nit), ''))           AS doc_numero,
            NULLIF(trim(tn.doc_dv), '')                  AS doc_dv,
            NULLIF(trim(tn.tipo_persona), '')            AS tipo_persona,
            NULLIF(trim(tn.regimen_iva), '')             AS regimen_iva,
            NULLIF(trim(tn.domicilio_direccion), '')     AS calle,
            NULLIF(trim(tn.domicilio_ciudad), '')        AS ciudad,
            NULLIF(trim(tn.domicilio_departamento), '')  AS depto,
            -- La columna trae el código ISO por defecto ('CO'), que en un documento
            -- para un comprador se lee como un error. Se expande al nombre.
            CASE upper(NULLIF(trim(tn.domicilio_pais), ''))
                WHEN 'CO' THEN 'Colombia'
                ELSE NULLIF(trim(tn.domicilio_pais), '')
            END                                          AS pais,
            NULLIF(trim(tn.email_contacto), '')          AS email,
            NULLIF(trim(tn.email_habeas_data), '')       AS email_habeas_data
        FROM public.tenants tn
        WHERE tn.id = p_tenant_id
    ),
    calc AS (
        SELECT
            COALESCE(t.razon_social, t.nombre_comercial) AS nombre,
            CASE WHEN t.doc_numero IS NULL THEN NULL
                 -- El guion solo si hay dígito de verificación: 'NIT 900123456-'
                 -- con el guion colgando delata un dato a medias.
                 WHEN t.doc_dv IS NULL THEN COALESCE(t.doc_tipo,'NIT') || ' ' || t.doc_numero
                 ELSE COALESCE(t.doc_tipo,'NIT') || ' ' || t.doc_numero || '-' || t.doc_dv
            END AS documento,
            -- Sin calle ni ciudad no hay dirección: 'Colombia' a secas no sirve
            -- para notificar judicialmente a nadie (art. 50 lit. a).
            CASE WHEN t.calle IS NULL AND t.ciudad IS NULL THEN NULL
                 ELSE array_to_string(
                        ARRAY(SELECT x FROM unnest(ARRAY[t.calle, t.ciudad, t.depto, t.pais]) x
                              WHERE x IS NOT NULL), ', ')
            END AS direccion,
            t.email, t.email_habeas_data, t.tipo_persona, t.regimen_iva,
            (t.razon_social IS NULL AND t.nombre_comercial IS NOT NULL) AS usa_nombre_comercial
        FROM t
    )
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'nombre',       c.nombre,
        'documento',    c.documento,
        'direccion',    c.direccion,
        'email',        c.email,
        'tipo_persona', c.tipo_persona,
        'regimen_iva',  c.regimen_iva,
        'email_habeas_data', c.email_habeas_data
    )) || jsonb_build_object(
        -- Fuera del strip_nulls: son banderas, y un false tiene que sobrevivir.
        'usa_nombre_comercial', COALESCE(c.usa_nombre_comercial, false),
        'completa', (c.nombre IS NOT NULL AND c.documento IS NOT NULL
                     AND c.direccion IS NOT NULL AND c.email IS NOT NULL),
        -- En palabras del comerciante: decirle "falta doc_dv" no le permite actuar.
        'faltantes', ARRAY(
            SELECT x FROM unnest(ARRAY[
                CASE WHEN c.nombre    IS NULL THEN 'razón social o nombre' END,
                CASE WHEN c.documento IS NULL THEN 'NIT o documento de identidad' END,
                CASE WHEN c.direccion IS NULL THEN 'dirección de notificación judicial' END,
                CASE WHEN c.email     IS NULL THEN 'correo de contacto' END
            ]) x WHERE x IS NOT NULL)
    )
    FROM calc c;
$$;

COMMENT ON FUNCTION public.tenant_seller_identity(UUID) IS
    'Identidad del vendedor para el comprobante (Ley 1480 art. 50 lit. a), con la '
    'cascada de degradación: razón social→nombre comercial, doc_numero→nit legado. '
    'Un campo ausente queda NULL para que el renderizador omita la línea entera. '
    '`faltantes` alimenta el aviso de la consola.';

REVOKE ALL ON FUNCTION public.tenant_seller_identity(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tenant_seller_identity(UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.tenant_seller_identity(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tenant_seller_identity(UUID) TO service_role;


-- ── 2. La tabla ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.order_receipts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    order_id      UUID NOT NULL REFERENCES public.orders(id)  ON DELETE CASCADE,
    numero_seq    BIGINT NOT NULL,
    numero        TEXT   NOT NULL,
    snapshot      JSONB  NOT NULL,
    content_hash  TEXT   NOT NULL,
    issued_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Anulación: un comprobante es una afirmación PENDIENTE, no un evento de fin
    -- de flujo. Si el pedido se cancela o se reembolsa después, el comprador se
    -- queda con un documento que afirma una compra que ya no existe.
    voided_at     TIMESTAMPTZ,
    void_reason   TEXT,
    -- Un comprobante por pedido. Es también la idempotencia de la emisión.
    CONSTRAINT order_receipts_uno_por_pedido UNIQUE (tenant_id, order_id),
    CONSTRAINT order_receipts_numero_unico   UNIQUE (tenant_id, numero_seq)
);

CREATE INDEX IF NOT EXISTS idx_order_receipts_tenant_emitido
    ON public.order_receipts (tenant_id, issued_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_receipts_anulados
    ON public.order_receipts (tenant_id, voided_at) WHERE voided_at IS NOT NULL;

COMMENT ON TABLE public.order_receipts IS
    'Comprobante de compra NO FISCAL (ADR-0040). `snapshot` congela el estado del '
    'mundo al emitir — vendedor incluido — porque un comprobante no puede cambiar '
    'porque el tenant editó su perfil después. NO es factura electrónica DIAN.';
COMMENT ON COLUMN public.order_receipts.numero IS
    'Consecutivo POR TENANT del comprobante, no del pedido: el bot cancela y recrea '
    'la orden pending_payment al cambiar el carrito, así que numerar allí dejaría '
    'huecos en pedidos que nunca existieron comercialmente.';

ALTER TABLE public.order_receipts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.order_receipts;
CREATE POLICY "Tenant Isolation" ON public.order_receipts
  FOR ALL USING (tenant_id = public.app_current_tenant())
         WITH CHECK (tenant_id = public.app_current_tenant());

-- Un comprobante emitido no se edita ni se borra desde la consola: es prueba de
-- una operación de consumo. Anularlo es un acto explícito (`rpc_void_receipt`),
-- que corre con service_role. Misma forma que las policies RESTRICTIVE de #165.
DROP POLICY IF EXISTS "receipts_no_escritura_directa" ON public.order_receipts;
CREATE POLICY "receipts_no_escritura_directa" ON public.order_receipts
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (true) WITH CHECK (false);

REVOKE INSERT, UPDATE, DELETE ON public.order_receipts FROM authenticated;
GRANT SELECT ON public.order_receipts TO authenticated;
GRANT ALL ON public.order_receipts TO service_role;

-- `anon` fuera, explícitamente. En el resto del esquema anon conserva los GRANT que
-- Supabase otorga por defecto y RLS es la frontera — verificado: ninguna tabla sin RLS
-- le es legible. Acá se va más allá a propósito: un comprobante congela PII del comprador
-- (nombre, teléfono, correo) junto con cifras de dinero, y es contenido inmutable con
-- valor probatorio. Si algún día alguien afloja una policy o desactiva RLS por error, esta
-- tabla no debe ser el agujero. La prueba de que RLS igual la protegería está en
-- tests/dbharness/test_order_receipts.py.
REVOKE ALL ON public.order_receipts FROM anon;


-- ── 3. Emitir ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_issue_receipt(
    p_order_id  UUID,
    p_tenant_id UUID
)
RETURNS TABLE (
    receipt_id UUID,
    numero     TEXT,
    ya_existia BOOLEAN,
    motivo     TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
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

    SELECT o.id, o.status, o.created_at, o.payment_method, o.contact_id, o.conversation_id
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
        'version', 1,
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

    INSERT INTO public.order_receipts
        (tenant_id, order_id, numero_seq, numero, snapshot, content_hash)
    VALUES
        (p_tenant_id, p_order_id, v_seq, v_numero, v_snapshot,
         encode(sha256(v_snapshot::text::bytea), 'hex'))
    RETURNING id INTO v_id;

    RETURN QUERY SELECT v_id, v_numero, false, NULL::TEXT;
END;
$$;

COMMENT ON FUNCTION public.rpc_issue_receipt(UUID, UUID) IS
    'Emite el comprobante de un pedido, idempotente por (tenant_id, order_id). NO '
    'emite si las cifras del pedido no cuadran (Ley 1480 art. 26): devuelve '
    'motivo=cifras_incoherentes. El consecutivo es del comprobante, no del pedido.';

REVOKE ALL ON FUNCTION public.rpc_issue_receipt(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_issue_receipt(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_issue_receipt(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_issue_receipt(UUID, UUID) TO service_role;


-- ── 4. Anular ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_void_receipt(
    p_order_id  UUID,
    p_tenant_id UUID,
    p_reason    TEXT
)
RETURNS TABLE (receipt_id UUID, numero TEXT, anulado BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v public.order_receipts%ROWTYPE;
BEGIN
    -- Solo el primer motivo se conserva: si un pedido se cancela y después se
    -- reembolsa, lo que anuló el comprobante fue la cancelación.
    UPDATE public.order_receipts
       SET voided_at = NOW(), void_reason = left(COALESCE(p_reason, 'sin_motivo'), 500)
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id AND voided_at IS NULL
    RETURNING * INTO v;

    IF FOUND THEN
        RETURN QUERY SELECT v.id, v.numero, true;
        RETURN;
    END IF;

    SELECT * INTO v FROM public.order_receipts
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id;
    RETURN QUERY SELECT v.id, v.numero, false;   -- no existía, o ya estaba anulado
END;
$$;

COMMENT ON FUNCTION public.rpc_void_receipt(UUID, UUID, TEXT) IS
    'Anula el comprobante de un pedido cancelado o reembolsado. Sin esto el '
    'comprador se queda con un documento que afirma una compra que ya no existe. '
    'Idempotente: conserva el motivo de la PRIMERA anulación.';

REVOKE ALL ON FUNCTION public.rpc_void_receipt(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_void_receipt(UUID, UUID, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_void_receipt(UUID, UUID, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_void_receipt(UUID, UUID, TEXT) TO service_role;
