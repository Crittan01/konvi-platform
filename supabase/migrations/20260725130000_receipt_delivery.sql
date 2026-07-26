-- ═══════════════════════════════════════════════════════════════════════════
-- Que el comprobante LLEGUE al comprador.  ADR-0040 paso 5.
--
-- Emitirlo y dejarlo en una tabla no cumple nada: Ley 1480 art. 50 lit. d) habla
-- de REMITIR el acuse de recibo, no de tenerlo disponible.
--
-- POR QUÉ WHATSAPP ES EL CANAL PRIMARIO — es cobertura, no estética:
--   • `contacts.phone` es NOT NULL; `contacts.email` es opcional.
--   • el envío de correo se salta EN SILENCIO cuando no hay dirección
--     (wompi_webhook.py: "contact sin email — skip").
-- WhatsApp llega al 100% de los compradores; el correo no.
--
-- PERO POR WHATSAPP VA UN ACUSE CORTO, NUNCA EL DOCUMENTO COMPLETO.
-- `messages` alimenta el contexto conversacional del LLM. Meter ahí 1.100-1.500
-- caracteres de cifras y cláusulas legales (a) cuesta tokens en CADA turno
-- posterior de esa conversación y (b) le da al modelo un documento lleno de
-- números para parafrasear o re-citar — choca de frente con el principio "el LLM
-- no decide verdad transaccional" y con el hallazgo de UAT del "total mentido".
-- El detalle completo va por correo y por la consola.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.order_receipts
    ADD COLUMN IF NOT EXISTS ack_sent_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ack_channel        TEXT,
    ADD COLUMN IF NOT EXISTS ack_skipped_reason TEXT;

COMMENT ON COLUMN public.order_receipts.ack_sent_at IS
    'Cuándo se le remitió el acuse al comprador (Ley 1480 art. 50 lit. d). NULL = '
    'todavía no salió. Es la idempotencia del envío: nadie recibe dos acuses.';
COMMENT ON COLUMN public.order_receipts.ack_skipped_reason IS
    'Por qué no se pudo remitir. Sin esto, un acuse que nunca sale es indistinguible '
    'de uno pendiente — y el plazo legal corre igual.';

CREATE INDEX IF NOT EXISTS idx_order_receipts_ack_pendiente
    ON public.order_receipts (tenant_id, issued_at)
    WHERE ack_sent_at IS NULL AND voided_at IS NULL;


-- ── A quién hay que escribirle ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_find_receipts_pending_ack(
    p_csw_hours INT DEFAULT 24,
    p_limit     INT DEFAULT 50
)
RETURNS TABLE (
    receipt_id      UUID,
    tenant_id       UUID,
    order_id        UUID,
    conversation_id UUID,
    numero          TEXT,
    total           NUMERIC,
    forma_pago      TEXT,
    dentro_de_csw   BOOLEAN
)
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT r.id, r.tenant_id, r.order_id, o.conversation_id, r.numero,
           (r.snapshot->'totales'->>'total')::NUMERIC,
           r.snapshot->'pedido'->>'forma_pago',
           -- Fuera de la ventana de servicio de Meta solo se puede escribir con
           -- plantilla aprobada, y las plantillas están diferidas (ADR-0040 §4).
           -- Se marca en vez de intentar y fallar con un error opaco de Meta.
           EXISTS (
               SELECT 1 FROM public.messages m
               WHERE m.conversation_id = o.conversation_id
                 AND m.direction = 'inbound'
                 AND m.created_at >= NOW() - make_interval(hours => p_csw_hours)
           )
    FROM public.order_receipts r
    JOIN public.orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    WHERE r.ack_sent_at IS NULL
      AND r.voided_at IS NULL          -- un comprobante anulado no se remite
      AND r.ack_skipped_reason IS NULL -- ya se decidió que no se podía
      AND o.conversation_id IS NOT NULL
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;

COMMENT ON FUNCTION public.rpc_find_receipts_pending_ack(INT, INT) IS
    'Comprobantes emitidos cuyo acuse todavía no le llegó al comprador. Excluye los '
    'anulados: remitir un documento que ya no es cierto sería peor que no remitirlo.';

REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_ack(INT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_ack(INT, INT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_find_receipts_pending_ack(INT, INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_find_receipts_pending_ack(INT, INT) TO service_role;


-- ── Marcar el resultado ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.rpc_mark_receipt_ack(
    p_receipt_id UUID,
    p_tenant_id  UUID,
    p_channel    TEXT,
    p_skipped    TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    UPDATE public.order_receipts
       SET ack_sent_at = CASE WHEN p_skipped IS NULL THEN NOW() ELSE NULL END,
           ack_channel = CASE WHEN p_skipped IS NULL THEN p_channel ELSE NULL END,
           ack_skipped_reason = left(p_skipped, 200)
     WHERE id = p_receipt_id AND tenant_id = p_tenant_id
       AND ack_sent_at IS NULL       -- nadie recibe dos acuses
    RETURNING true;
$$;

COMMENT ON FUNCTION public.rpc_mark_receipt_ack(UUID, UUID, TEXT, TEXT) IS
    'Registra que el acuse salió (o por qué no). El guard ack_sent_at IS NULL es la '
    'idempotencia: un reintento del barrido no le manda dos acuses al mismo comprador.';

REVOKE ALL ON FUNCTION public.rpc_mark_receipt_ack(UUID, UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_mark_receipt_ack(UUID, UUID, TEXT, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.rpc_mark_receipt_ack(UUID, UUID, TEXT, TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_mark_receipt_ack(UUID, UUID, TEXT, TEXT) TO service_role;
