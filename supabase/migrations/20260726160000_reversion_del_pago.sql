-- ═══════════════════════════════════════════════════════════════════════════
-- La reversión del pago: una figura DISTINTA del reembolso comercial.
--
-- EL PROBLEMA
-- Hoy el sistema solo sabe hacer una cosa cuando algo sale mal: devolver plata
-- (`order_cancellations.refund_*`). Pero la ley colombiana tiene DOS caminos, y el
-- que falta es el que el consumidor puede ejercer sin nuestro permiso:
--
--   · REEMBOLSO comercial  → nosotros devolvemos. Depende de nuestra voluntad y
--                            capacidad de pagar.
--   · REVERSIÓN del pago   → el consumidor le pide al EMISOR de su tarjeta que
--                            deshaga el cargo. Nosotros no la ejecutamos.
--
-- Y en la reversión tenemos UNA obligación concreta e ineludible:
--
--     Decreto 1074 art. 2.2.2.51.4 (verificado 2026-07-26 en el texto oficial del
--     Decreto 587 de 2016, funcionpublica.gov.co/eva/gestornormativo):
--     "Cualquiera fuere el medio utilizado para interponer la queja, el proveedor
--      deberá emitir CONSTANCIA de la presentación de la misma, con indicación de
--      la FECHA y CAUSAL que la sustentan."
--
-- Esa constancia no es un trámite: el art. 2.2.2.51.7 num. 6 la exige como
-- contenido de la notificación que el consumidor le presenta a su banco. SIN
-- NUESTRA CONSTANCIA, EL CONSUMIDOR NO PUEDE EJERCER SU DERECHO. Hoy alguien
-- escribe por WhatsApp "me llegó dañado, quiero que me devuelvan la plata" y no
-- se emite nada.
--
-- ── LAS CINCO CAUSALES SON UNA LISTA CERRADA ───────────────────────────────
-- Art. 2.2.2.51.2: fraude, operación no solicitada, producto no recibido, producto
-- que no corresponde a lo solicitado, producto defectuoso. Ni una más.
--
-- La causal la DECLARA el consumidor, no la infiere el bot. Además de ser lo que
-- dice la norma ("indicación de la causal que sustenta la petición"), poner un LLM
-- a clasificar en qué casilla legal cae una frase es exactamente lo que este
-- proyecto no hace: el LLM no decide verdad transaccional (ADR-0024).
--
-- ── DÓNDE NO PROCEDE, Y POR QUÉ IMPORTA DECIRLO ────────────────────────────
-- Art. 2.2.2.51.1: la reversión "no procede cuando [los pagos] hayan sido
-- realizados por medio de canales presenciales". Contra entrega en efectivo es
-- presencial: ahí no hay instrumento de pago electrónico que reversar, y el camino
-- es el reembolso comercial.
--
-- Registrar una "reversión" sobre un pedido pagado en efectivo le prometería al
-- comprador un derecho que no tiene — el mismo error que se corrigió en #192,
-- donde le declarábamos plazos ajenos. Por eso la RPC se NIEGA y lo dice.
--
-- ── EL DOBLE PAGO ───────────────────────────────────────────────────────────
-- Art. 2.2.2.51.10: "En caso de que proceda la reversión del pago por parte del
-- emisor del instrumento de pago Y el proveedor haya realizado directamente la
-- devolución del precio pagado, el consumidor será responsable de devolver los
-- recursos directamente al proveedor."
--
-- O sea: la norma contempla que el comerciante pague dos veces. Es un escenario
-- REAL —el operador reembolsa por su cuenta mientras el banco reversa en paralelo—
-- y hoy sería invisible: nadie está mirando las dos cosas al tiempo. Acá se
-- registran ambas y se marca la colisión, porque no se puede reclamar lo que no se
-- sabe que se pagó.
-- ═══════════════════════════════════════════════════════════════════════════


-- ── 1. La solicitud de reversión ───────────────────────────────────────────
--
-- Tabla propia y no columnas sobre `claims`, por la misma razón por la que
-- `order_receipts` no vive dentro de `orders`: es un documento legal congelado con
-- sus propias reglas, no un atributo del reclamo. El reclamo sigue siendo la
-- bandeja del operador; esto es la pieza jurídica que cuelga de él.

CREATE TABLE IF NOT EXISTS public.payment_reversal_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    claim_id      UUID NOT NULL REFERENCES public.claims(id) ON DELETE CASCADE,
    order_id      UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,

    -- El radicado NO estrena numeración: es el ticket del reclamo en otra
    -- presentación. Dos números para el mismo reclamo es cómo se pierde la pista de
    -- cuál le dio el operador al cliente por teléfono.
    radicado      TEXT NOT NULL,

    -- Lista CERRADA del art. 2.2.2.51.2. Un CHECK y no un enum: agregar valores a un
    -- enum en PostgreSQL no se puede deshacer dentro de una transacción, y esta lista
    -- solo cambia si cambia la ley.
    causal        TEXT NOT NULL CHECK (causal IN (
        'fraude',                    -- num. 1
        'operacion_no_solicitada',   -- num. 2
        'producto_no_recibido',      -- num. 3
        'producto_no_corresponde',   -- num. 4 (tampoco cumple lo informado)
        'producto_defectuoso'        -- num. 5
    )),

    -- Art. 2.2.2.51.5 num. 1: "manifestación expresa de las razones". En las
    -- palabras del consumidor; no se resume ni se reinterpreta.
    razones       TEXT NOT NULL CHECK (length(btrim(razones)) >= 3),

    -- Art. 2.2.2.51.5 num. 3 y art. 2.2.2.51.3: el valor. Puede ser parcial cuando
    -- la compra tuvo varios productos y solo algunos tienen causal.
    valor         NUMERIC(14,2) NOT NULL CHECK (valor > 0),
    es_parcial    BOOLEAN NOT NULL DEFAULT FALSE,
    items_json    JSONB,

    -- Art. 2.2.2.51.5 num. 4: identificación del instrumento al que se cargó la
    -- operación. DESCRIPTOR, nunca el número: guardar un PAN sería crear una
    -- obligación PCI que este sistema no tiene por qué asumir.
    instrumento   TEXT,

    -- La fecha es la mitad del contenido obligatorio de la constancia, y además la
    -- que prueba que la queja entró dentro de los 5 días hábiles del art. 2.2.2.51.4.
    presentada_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    canal         TEXT NOT NULL DEFAULT 'whatsapp',

    -- Evidencia de que la queja existió, con el mismo criterio que la aceptación del
    -- pedido: puntero al mensaje y al id que le asignó Meta (atestación de un tercero).
    conversation_id  UUID REFERENCES public.conversations(id) ON DELETE SET NULL,
    message_id       UUID,
    meta_message_id  TEXT,

    -- La constancia, congelada. Igual que el comprobante: si mañana cambia el texto,
    -- las constancias ya emitidas siguen diciendo lo que dijeron.
    constancia          JSONB,
    constancia_hash     TEXT,
    constancia_emitida_at TIMESTAMPTZ,
    constancia_entregada_at TIMESTAMPTZ,
    constancia_entrega_fallida TEXT,

    -- Art. 2.2.2.51.4 inc. 3: tratándose de bienes, el consumidor indica que el bien
    -- queda a disposición para recogerlo "en las mismas condiciones y en el mismo
    -- lugar en que se recibió, con lo cual se entenderá satisfecha la obligación de
    -- devolverlo". Se registra porque es lo que libera al consumidor de la devolución.
    bien_a_disposicion BOOLEAN NOT NULL DEFAULT FALSE,

    -- Los dos caminos por los que puede salir la plata. Tenerlos separados es lo que
    -- permite ver el doble pago del art. 2.2.2.51.10.
    reembolso_directo_at    TIMESTAMPTZ,
    reembolso_directo_valor NUMERIC(14,2),
    reversion_confirmada_at TIMESTAMPTZ,
    reversion_valor         NUMERIC(14,2),
    doble_pago_detectado_at TIMESTAMPTZ,
    doble_pago_avisado_at   TIMESTAMPTZ,

    estado TEXT NOT NULL DEFAULT 'presentada' CHECK (estado IN (
        'presentada',   -- el consumidor la radicó; hay constancia
        'notificada',   -- el consumidor avisó a su emisor (nos lo informó)
        'resuelta',     -- la plata volvió, por el camino que fuera
        'controvertida',-- art. 2.2.2.51.9: hay disputa ante autoridad
        'desistida'
    )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Un reclamo da lugar a UNA solicitud de reversión. Reintentar la radicación no
    -- puede producirle al consumidor dos constancias con fechas distintas: la fecha
    -- es lo que prueba que llegó dentro de los 5 días hábiles.
    CONSTRAINT payment_reversal_requests_claim_unico UNIQUE (claim_id)
);

COMMENT ON TABLE public.payment_reversal_requests IS
    'Solicitudes de reversión del pago (Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51). '
    'Figura DISTINTA del reembolso comercial: acá el dinero lo devuelve el emisor del '
    'instrumento de pago, no el comerciante. Nuestra obligación es emitir la constancia.';
COMMENT ON COLUMN public.payment_reversal_requests.instrumento IS
    'Descriptor del medio de pago (p. ej. "Visa terminada en 4242"), NUNCA el número '
    'completo: guardar un PAN crearía una obligación PCI que este sistema no asume.';
COMMENT ON COLUMN public.payment_reversal_requests.doble_pago_detectado_at IS
    'Cuándo se detectó que el dinero salió por los DOS caminos a la vez (art. 2.2.2.51.10). '
    'No se puede reclamar lo que no se sabe que se pagó.';

CREATE INDEX IF NOT EXISTS idx_reversal_tenant_estado
    ON public.payment_reversal_requests (tenant_id, estado, presentada_at DESC);
CREATE INDEX IF NOT EXISTS idx_reversal_order
    ON public.payment_reversal_requests (order_id);
-- El barrido del worker busca constancias emitidas y aún no entregadas.
CREATE INDEX IF NOT EXISTS idx_reversal_constancia_sin_entregar
    ON public.payment_reversal_requests (tenant_id, constancia_emitida_at)
    WHERE constancia_emitida_at IS NOT NULL AND constancia_entregada_at IS NULL;
-- Y el de alertas, los dobles pagos sin avisar.
CREATE INDEX IF NOT EXISTS idx_reversal_doble_pago
    ON public.payment_reversal_requests (tenant_id)
    WHERE doble_pago_detectado_at IS NOT NULL;

DROP TRIGGER IF EXISTS trg_reversal_updated_at ON public.payment_reversal_requests;
CREATE TRIGGER trg_reversal_updated_at
    BEFORE UPDATE ON public.payment_reversal_requests
    FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();


-- ── 2. Aislamiento ─────────────────────────────────────────────────────────

-- Sin FORCE, igual que `order_receipts` y `orders`. Con FORCE, la RLS también aplicaría
-- al dueño de la tabla, y las RPC SECURITY DEFINER corren precisamente como el dueño: la
-- función que EMITE la constancia quedaría bloqueada por la política que impide escribirla
-- a mano. El aislamiento real lo dan las políticas + el lint AST (ADR-0025).
ALTER TABLE public.payment_reversal_requests ENABLE ROW LEVEL SECURITY;

-- Mismo patrón que `order_receipts`, que es el otro documento legal congelado del
-- sistema: se lee lo propio y NO se escribe directo ni siendo dueño del tenant. La
-- constancia la emite la RPC o no existe.
DROP POLICY IF EXISTS "Tenant Isolation" ON public.payment_reversal_requests;
CREATE POLICY "Tenant Isolation" ON public.payment_reversal_requests
    FOR SELECT USING (tenant_id = public.app_current_tenant());

-- RESTRICTIVE, no permissive. Las políticas permisivas se combinan con OR: una segunda
-- política `USING (true)` habría ANULADO el aislamiento por tenant en lugar de sumarle una
-- restricción. Se escribió así primero y el test de RLS lo cazó — otro tenant veía la
-- constancia ajena.
DROP POLICY IF EXISTS reversal_no_escritura_directa ON public.payment_reversal_requests;
CREATE POLICY reversal_no_escritura_directa ON public.payment_reversal_requests
    AS RESTRICTIVE FOR ALL TO authenticated USING (true) WITH CHECK (false);

-- Escribir una solicitud de reversión es emitir un documento legal: pasa por las RPC,
-- que son las que garantizan constancia, radicado y coherencia. Nadie la inserta a mano.
-- El REVOKE a `authenticated` no es redundante: sin ALTER DEFAULT PRIVILEGES, toda
-- tabla nueva nace con los GRANTs que el esquema reparte, y "no se escribe a mano"
-- habría sido falso. Es la misma causa raíz de las dos vulnerabilidades de #162/#164.
REVOKE ALL ON public.payment_reversal_requests FROM PUBLIC;
REVOKE ALL ON public.payment_reversal_requests FROM anon;
REVOKE ALL ON public.payment_reversal_requests FROM authenticated;
GRANT SELECT ON public.payment_reversal_requests TO authenticated;
GRANT ALL ON public.payment_reversal_requests TO service_role;


-- ── 3. ¿Procede la reversión sobre este pedido? ────────────────────────────

CREATE OR REPLACE FUNCTION public.reversion_procede(p_order_id UUID, p_tenant_id UUID)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_metodo TEXT;
BEGIN
    SELECT o.payment_method INTO v_metodo
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN 'pedido_inexistente';
    END IF;

    -- Art. 2.2.2.51.1: "no procede cuando hayan sido realizados por medio de canales
    -- presenciales". Contra entrega en efectivo es presencial — no hay instrumento de
    -- pago electrónico que reversar. El camino ahí es el reembolso comercial, y decirle
    -- otra cosa al comprador sería prometerle un derecho que no tiene.
    -- El CHECK de `orders` hoy solo admite 'credit' y 'cod'. Los sinónimos se dejan
    -- porque un canal nuevo (Nequi, transferencia) entrará por acá antes de que nadie se
    -- acuerde de esta función, y el modo seguro de fallar es NO radicar.
    IF COALESCE(v_metodo, '') IN ('cod', 'cash', 'efectivo') THEN
        RETURN 'pago_no_electronico';
    END IF;

    -- Sin forma de pago registrada no se puede afirmar que fue electrónico. Se prefiere
    -- no radicar a radicar sobre un supuesto: la constancia afirma hechos.
    IF COALESCE(btrim(v_metodo), '') = '' THEN
        RETURN 'forma_de_pago_desconocida';
    END IF;

    RETURN 'procede';
END;
$$;

COMMENT ON FUNCTION public.reversion_procede(UUID, UUID) IS
    'Devuelve "procede" o el motivo por el que no. Decreto 1074 art. 2.2.2.51.1: la '
    'reversión no aplica a pagos por canales presenciales (contra entrega en efectivo).';

REVOKE ALL ON FUNCTION public.reversion_procede(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reversion_procede(UUID, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.reversion_procede(UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.reversion_procede(UUID, UUID) TO service_role;


-- ── 4. Radicar la queja y emitir la constancia, en un solo acto ────────────
--
-- No son dos pasos. El art. 2.2.2.51.4 no condiciona la constancia a nada: si la
-- queja se presentó, la constancia se debe. Separarlos crearía el estado "queja
-- radicada sin constancia", que es precisamente el incumplimiento.

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
        -- La reversión se predica de una compra concreta: sin pedido no hay operación
        -- que reversar ni valor que reclamar.
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'reclamo_sin_pedido'::TEXT;
        RETURN;
    END IF;

    -- Idempotente ANTES de validar nada más: un reintento no puede producir una
    -- segunda constancia con otra fecha. La fecha es lo que prueba que la queja llegó
    -- dentro de los 5 días hábiles del art. 2.2.2.51.4.
    SELECT r.id, r.radicado INTO v_existente
      FROM public.payment_reversal_requests r
     WHERE r.claim_id = p_claim_id AND r.tenant_id = p_tenant_id;
    IF FOUND THEN
        RETURN QUERY SELECT v_existente.id, v_existente.radicado, true, NULL::TEXT;
        RETURN;
    END IF;

    v_procede := public.reversion_procede(v_claim.order_id, p_tenant_id);
    IF v_procede <> 'procede' THEN
        -- El reclamo sigue vivo como reclamo; lo que no procede es ESTA figura.
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, v_procede;
        RETURN;
    END IF;

    -- El valor reclamado no puede exceder lo que se pagó. Una constancia que pida
    -- reversar más que el total le entrega al emisor un motivo para rechazarla entera
    -- (art. 2.2.2.51.8: es oponible "la inexistencia de la operación").
    SELECT o.total_amount INTO v_total
      FROM public.orders o WHERE o.id = v_claim.order_id AND o.tenant_id = p_tenant_id;
    IF v_total IS NOT NULL AND p_valor > v_total THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'valor_excede_el_pedido'::TEXT;
        RETURN;
    END IF;

    -- Un solo número para el mismo reclamo, en otra presentación.
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

    -- LA CONSTANCIA. Contenido mínimo del art. 2.2.2.51.4: fecha y causal. Se agrega
    -- lo que el consumidor necesita para armar su notificación al emisor (art.
    -- 2.2.2.51.7): valor, identificación de la operación y del instrumento.
    v_constancia := jsonb_build_object(
        'version', 1,
        'radicado', v_radicado,
        -- Hora COLOMBIA explícita. El servidor corre en UTC y una queja presentada un
        -- viernes a las 8 de la noche quedaría fechada el sábado, corriendo el conteo
        -- de días hábiles en contra del consumidor.
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

COMMENT ON FUNCTION public.rpc_registrar_reversion IS
    'Radica la queja de reversión y emite su constancia en el MISMO acto: el art. '
    '2.2.2.51.4 no condiciona la constancia a nada, y "radicada sin constancia" es '
    'justamente el incumplimiento. Idempotente por reclamo.';

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


-- ── 5. Por dónde salió la plata, y si salió dos veces ──────────────────────

CREATE OR REPLACE FUNCTION public.rpc_registrar_movimiento_reversion(
    p_reversal_id UUID,
    p_tenant_id   UUID,
    p_via         TEXT,      -- 'reembolso_directo' | 'reversion_emisor'
    p_valor       NUMERIC
)
RETURNS TABLE (doble_pago BOOLEAN, motivo TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_fila RECORD;
    v_doble BOOLEAN := false;
BEGIN
    SELECT * INTO v_fila
      FROM public.payment_reversal_requests
     WHERE id = p_reversal_id AND tenant_id = p_tenant_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'reversion_inexistente'::TEXT;
        RETURN;
    END IF;
    IF p_via NOT IN ('reembolso_directo', 'reversion_emisor') THEN
        RETURN QUERY SELECT false, 'via_desconocida'::TEXT;
        RETURN;
    END IF;

    IF p_via = 'reembolso_directo' THEN
        UPDATE public.payment_reversal_requests
           SET reembolso_directo_at = COALESCE(reembolso_directo_at, NOW()),
               reembolso_directo_valor = COALESCE(reembolso_directo_valor, p_valor)
         WHERE id = p_reversal_id;
    ELSE
        UPDATE public.payment_reversal_requests
           SET reversion_confirmada_at = COALESCE(reversion_confirmada_at, NOW()),
               reversion_valor = COALESCE(reversion_valor, p_valor)
         WHERE id = p_reversal_id;
    END IF;

    -- Art. 2.2.2.51.10: la norma contempla expresamente que el dinero salga por los
    -- dos caminos. Es real —el operador reembolsa mientras el banco reversa en
    -- paralelo— y hoy sería invisible porque nadie mira las dos cosas al tiempo.
    SELECT (reembolso_directo_at IS NOT NULL AND reversion_confirmada_at IS NOT NULL)
      INTO v_doble
      FROM public.payment_reversal_requests WHERE id = p_reversal_id;

    UPDATE public.payment_reversal_requests
       SET doble_pago_detectado_at = CASE
               WHEN v_doble THEN COALESCE(doble_pago_detectado_at, NOW())
               ELSE doble_pago_detectado_at END,
           estado = CASE WHEN estado IN ('presentada','notificada') THEN 'resuelta'
                         ELSE estado END
     WHERE id = p_reversal_id;

    RETURN QUERY SELECT v_doble, NULL::TEXT;
END;
$$;

COMMENT ON FUNCTION public.rpc_registrar_movimiento_reversion(UUID, UUID, TEXT, NUMERIC) IS
    'Registra por cuál de los dos caminos volvió el dinero y marca la colisión cuando '
    'volvió por los dos (Decreto 1074 art. 2.2.2.51.10). No se puede reclamar lo que no '
    'se sabe que se pagó.';

REVOKE ALL ON FUNCTION public.rpc_registrar_movimiento_reversion(UUID, UUID, TEXT, NUMERIC) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_registrar_movimiento_reversion(UUID, UUID, TEXT, NUMERIC) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_registrar_movimiento_reversion(UUID, UUID, TEXT, NUMERIC) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_registrar_movimiento_reversion(UUID, UUID, TEXT, NUMERIC) TO service_role;


-- ── 6. Lo que el worker sale a buscar ──────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_find_constancias_por_entregar(p_limit INTEGER DEFAULT 50)
RETURNS TABLE (
    reversal_id UUID, tenant_id UUID, conversation_id UUID,
    radicado TEXT, constancia JSONB
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT r.id, r.tenant_id, r.conversation_id, r.radicado, r.constancia
      FROM public.payment_reversal_requests r
     WHERE r.constancia_emitida_at IS NOT NULL
       AND r.constancia_entregada_at IS NULL
       AND r.constancia_entrega_fallida IS NULL
       AND r.conversation_id IS NOT NULL
     ORDER BY r.constancia_emitida_at
     LIMIT GREATEST(p_limit, 1);
$$;

CREATE OR REPLACE FUNCTION public.rpc_find_dobles_pagos_sin_avisar(p_limit INTEGER DEFAULT 50)
RETURNS TABLE (
    reversal_id UUID, tenant_id UUID, radicado TEXT,
    reembolso NUMERIC, reversion NUMERIC
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT r.id, r.tenant_id, r.radicado, r.reembolso_directo_valor, r.reversion_valor
      FROM public.payment_reversal_requests r
     WHERE r.doble_pago_detectado_at IS NOT NULL
       AND r.doble_pago_avisado_at IS NULL
     ORDER BY r.doble_pago_detectado_at
     LIMIT GREATEST(p_limit, 1);
$$;

REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_constancias_por_entregar(INTEGER) TO service_role;

REVOKE ALL ON FUNCTION public.rpc_find_dobles_pagos_sin_avisar(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_dobles_pagos_sin_avisar(INTEGER) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_dobles_pagos_sin_avisar(INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_dobles_pagos_sin_avisar(INTEGER) TO service_role;


-- ── 7. Marcar lo entregado y lo avisado ────────────────────────────────────
--
-- Compare-and-set, no UPDATE ciego: dos ticks del worker pueden mirar la misma fila. El
-- que pierde la carrera recibe FALSE y no vuelve a persistir el mensaje. Es el mismo
-- patrón de `rpc_mark_receipt_ack`, por la misma razón.

CREATE OR REPLACE FUNCTION public.rpc_mark_constancia_entregada(
    p_reversal_id UUID,
    p_tenant_id   UUID,
    p_fallida     TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_n INTEGER;
BEGIN
    UPDATE public.payment_reversal_requests
       SET constancia_entregada_at = CASE WHEN p_fallida IS NULL THEN NOW() END,
           constancia_entrega_fallida = p_fallida
     WHERE id = p_reversal_id
       AND tenant_id = p_tenant_id
       AND constancia_entregada_at IS NULL
       AND constancia_entrega_fallida IS NULL;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.rpc_mark_doble_pago_avisado(
    p_reversal_id UUID,
    p_tenant_id   UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_n INTEGER;
BEGIN
    UPDATE public.payment_reversal_requests
       SET doble_pago_avisado_at = NOW()
     WHERE id = p_reversal_id AND tenant_id = p_tenant_id
       AND doble_pago_detectado_at IS NOT NULL
       AND doble_pago_avisado_at IS NULL;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_mark_constancia_entregada(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_mark_constancia_entregada(UUID, UUID, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_mark_constancia_entregada(UUID, UUID, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_mark_constancia_entregada(UUID, UUID, TEXT) TO service_role;

REVOKE ALL ON FUNCTION public.rpc_mark_doble_pago_avisado(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_mark_doble_pago_avisado(UUID, UUID) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_mark_doble_pago_avisado(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_mark_doble_pago_avisado(UUID, UUID) TO service_role;
