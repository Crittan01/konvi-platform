-- ═══════════════════════════════════════════════════════════════════════════
-- Detector de "cliente mudo": el cliente escribió y NADIE le respondió.
--
-- PROBLEMA
-- Hay al menos seis caminos por los que un inbound termina sin respuesta que
-- llegue al cliente (envío que devuelve None, cola outbound que agota intentos,
-- rate limit, degradación del LLM sin emitir, gate de estado, crash entre
-- "processed" y el envío). Cada uno se loguea distinto — o no se loguea — y
-- ninguno le avisa a un humano. El cliente escribe, no recibe nada, y se va.
--
-- Los sweepers que ya existen NO cubren esto:
--   • _reclaim_stale_inbound recupera mensajes que quedaron SIN PROCESAR.
--   • el tracker de SLA vigila conversaciones YA escaladas a human_takeover.
-- El hueco es justo el del medio: el inbound se procesó "bien" y aun así al
-- cliente no le llegó nada.
--
-- ESTA FUNCIÓN
-- Detecta el síntoma (silencio) en vez de cada causa, así que cubre los seis
-- caminos a la vez y también los que aparezcan mañana.
--
-- CRITERIO DE "SÍ LE RESPONDIMOS"
-- Existe un outbound posterior al último inbound que:
--   • tiene meta_message_id NOT NULL  → Meta lo aceptó, es prueba de entrega
--     (lo estampa _mark_outbound_sent; _mark_outbound_failed lo deja NULL), o
--   • sigue en vuelo (pending/processing) → todavía no es silencio, es demora.
-- Las filas de auditoría (escalation_audit, sla_breach_audit…) van con
-- direction='outbound' pero NO son mensajes al cliente — se excluyen, si no
-- una escalada previa taparía el silencio que buscamos.
--
-- POR QUÉ SQL Y NO N+1 EN PYTHON
-- La DB está en otra región (~65ms por query): 25 conversaciones × 2 queries
-- serían ~3s por barrido. Set-based es una sola ida y usa
-- idx_messages_conversation_created (conversation_id, created_at DESC).
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.rpc_find_silent_conversations(
    p_silence_minutes INT DEFAULT 10,
    p_window_hours    INT DEFAULT 24,
    p_limit           INT DEFAULT 25
)
RETURNS TABLE (
    conversation_id  UUID,
    tenant_id        UUID,
    customer_phone   TEXT,
    last_inbound_at  TIMESTAMPTZ,
    silence_minutes  INT
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    WITH last_inbound AS (
        -- Último inbound por conversación, ya en estado terminal. Si sigue en
        -- 'pending'/'processing' es trabajo de _reclaim_stale_inbound, no de
        -- este detector: alertar ahí sería competir con el reintento en curso.
        SELECT DISTINCT ON (m.conversation_id)
               m.conversation_id,
               m.tenant_id,
               m.created_at
        FROM public.messages m
        WHERE m.direction = 'inbound'
          AND m.processing_status IN ('processed', 'failed')
          -- Cota superior: fuera de la ventana de servicio de Meta ya no
          -- podríamos responder free-form, así que alertar no sirve de nada.
          AND m.created_at >= NOW() - make_interval(hours => p_window_hours)
          AND m.created_at <= NOW() - make_interval(mins  => p_silence_minutes)
        ORDER BY m.conversation_id, m.created_at DESC
    )
    SELECT li.conversation_id,
           li.tenant_id,
           c.customer_phone,
           li.created_at,
           (EXTRACT(EPOCH FROM (NOW() - li.created_at)) / 60)::INT
    FROM last_inbound li
    JOIN public.conversations c ON c.id = li.conversation_id
    WHERE
        -- human_takeover ya lo vigila el tracker de SLA; en closed/opted_out el
        -- silencio es correcto (el cliente pidió la baja o la conv se archivó).
        c.status NOT IN ('human_takeover', 'closed', 'opted_out')
      AND NOT EXISTS (
            SELECT 1
            FROM public.messages o
            WHERE o.conversation_id = li.conversation_id
              AND o.direction = 'outbound'
              AND o.created_at >= li.created_at
              AND o.content_type NOT LIKE '%audit%'
              AND (
                    o.meta_message_id IS NOT NULL
                 OR o.processing_status IN ('pending', 'processing')
              )
        )
        -- Idempotencia: una alerta por episodio de silencio. Sin esto el
        -- barrido re-alertaría cada 5 min sobre la misma conversación durante
        -- 24h y el ruido enterraría los casos nuevos.
      AND NOT EXISTS (
            SELECT 1
            FROM public.messages a
            WHERE a.conversation_id = li.conversation_id
              AND a.content_type = 'silent_conversation_audit'
              AND a.created_at >= li.created_at
        )
    ORDER BY li.created_at ASC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_silent_conversations(INT, INT, INT) IS
    'Conversaciones donde el cliente escribió y no le llegó respuesta. '
    'Detecta el síntoma, no la causa: cubre los seis caminos conocidos de '
    'mensaje perdido y los que aparezcan después. La consume el worker '
    '(_detect_silent_conversations_if_due) para escalar a un humano.';

-- Solo el backend. Un tenant no debe poder barrer conversaciones vía PostgREST:
-- la función es STABLE y cross-tenant por diseño (la corre un cron sin JWT),
-- así que exponerla sería una fuga de metadatos entre tenants.
REVOKE ALL ON FUNCTION public.rpc_find_silent_conversations(INT, INT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_silent_conversations(INT, INT, INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_silent_conversations(INT, INT, INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_silent_conversations(INT, INT, INT) TO service_role;
