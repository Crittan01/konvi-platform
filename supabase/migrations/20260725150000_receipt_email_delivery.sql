-- ═══════════════════════════════════════════════════════════════════════════
-- El detalle completo del comprobante, por correo.  ADR-0040 paso 6.
--
-- El acuse por WhatsApp (paso 5) es corto a propósito: `messages` alimenta el
-- contexto del LLM y meter ahí un documento lleno de cifras costaría tokens en
-- cada turno y le daría al modelo números para parafrasear. El detalle completo
-- va por correo — y esta migración es lo que lo hace posible.
--
-- POR QUÉ COLUMNAS NUEVAS Y NO REUSAR `ack_channel`
-- No es preferencia de estilo; el estado compartido NO PUEDE representar la
-- realidad de dos canales:
--   1. `rpc_mark_receipt_ack` marca con guarda `AND ack_sent_at IS NULL`. Con dos
--      canales compitiendo, el segundo pierde y se pierde el hecho de que salió.
--   2. Con `p_skipped` no nulo la RPC fuerza `ack_sent_at` Y `ack_channel` a NULL,
--      así que el estado "WhatsApp saltado, correo enviado" es inexpresable.
--   3. `rpc_find_receipts_pending_ack` excluye `ack_skipped_reason IS NOT NULL`.
--
-- Y el punto 3 tiene una consecuencia que hay que decir con todas las letras:
-- HOY EL WORKER MIENTE. Cuando un comprobante queda fuera de la ventana de 24h de
-- Meta, loguea "Queda disponible en la consola y por correo" — pero esa fila queda
-- excluida del barrido para siempre y no existe ningún camino de correo. Esta
-- migración convierte esa promesa en verdad: la población que WhatsApp no pudo
-- alcanzar es exactamente la que el correo viene a rescatar.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.order_receipts
    ADD COLUMN IF NOT EXISTS email_sent_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_to             TEXT,
    ADD COLUMN IF NOT EXISTS email_skipped_reason TEXT;

COMMENT ON COLUMN public.order_receipts.email_sent_at IS
    'Cuándo salió el correo con el detalle completo. Independiente de ack_sent_at: '
    'son dos canales y un comprobante puede haber llegado por uno y no por el otro.';
COMMENT ON COLUMN public.order_receipts.email_skipped_reason IS
    'Por qué no se pudo enviar (típicamente: el comprador no tiene correo). Sin esto, '
    'un correo que nunca sale es indistinguible de uno pendiente.';

CREATE INDEX IF NOT EXISTS idx_order_receipts_email_pendiente
    ON public.order_receipts (tenant_id, issued_at)
    WHERE email_sent_at IS NULL AND email_skipped_reason IS NULL AND voided_at IS NULL;


-- ── A quién hay que escribirle ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_find_receipts_pending_email(
    p_limit INT DEFAULT 50
)
RETURNS TABLE (
    receipt_id UUID,
    tenant_id  UUID,
    numero     TEXT,
    snapshot   JSONB,
    email      TEXT
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT r.id, r.tenant_id, r.numero, r.snapshot,
           NULLIF(trim(c.email), '')
    FROM public.order_receipts r
    JOIN public.orders   o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    LEFT JOIN public.contacts c ON c.id = o.contact_id AND c.tenant_id = r.tenant_id
    WHERE r.email_sent_at IS NULL
      AND r.email_skipped_reason IS NULL
      -- Un comprobante anulado no se remite: mandar un documento que ya no es
      -- cierto sería peor que no mandarlo.
      AND r.voided_at IS NULL
      -- A propósito NO se filtra por el estado del acuse de WhatsApp: los dos
      -- canales son independientes, y los que WhatsApp no alcanzó son justamente
      -- los que más necesitan el correo.
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_receipts_pending_email(INT) IS
    'Comprobantes cuyo detalle completo todavía no salió por correo. Devuelve el email '
    'en NULL cuando el comprador no tiene: el caller lo marca como saltado con motivo, '
    'en vez de dejarlo pendiente para siempre.';

REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_email(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_email(INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_email(INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_receipts_pending_email(INT) TO service_role;


-- ── Marcar el resultado ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_mark_receipt_email(
    p_receipt_id UUID,
    p_tenant_id  UUID,
    p_email      TEXT DEFAULT NULL,
    p_skipped    TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    UPDATE public.order_receipts
       SET email_sent_at = CASE WHEN p_skipped IS NULL THEN NOW() ELSE NULL END,
           email_to      = CASE WHEN p_skipped IS NULL THEN left(p_email, 320) ELSE NULL END,
           email_skipped_reason = left(p_skipped, 200)
     WHERE id = p_receipt_id AND tenant_id = p_tenant_id
       AND email_sent_at IS NULL     -- nadie recibe dos veces el mismo comprobante
    RETURNING true;
$$;

COMMENT ON FUNCTION public.rpc_mark_receipt_email(UUID, UUID, TEXT, TEXT) IS
    'Registra que el correo salió (o por qué no). El guard email_sent_at IS NULL es la '
    'idempotencia: un reintento del barrido no le manda dos veces el mismo documento.';

REVOKE ALL ON FUNCTION public.rpc_mark_receipt_email(UUID, UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_mark_receipt_email(UUID, UUID, TEXT, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_mark_receipt_email(UUID, UUID, TEXT, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_mark_receipt_email(UUID, UUID, TEXT, TEXT) TO service_role;
