-- Rev. 78 — RPC para liberar todas las reservas activas de una conversación.
--
-- Contexto: cuando Wompi notifica DECLINED/VOIDED/ERROR, el orden queda en
-- pending_payment pero las reservas siguen `active` ligadas por
-- conversation_id (order_id solo se setea en consume durante APPROVED).
-- Sin esta liberación explícita, el stock queda bloqueado hasta el TTL 35min.
--
-- Reusable también para:
--   • Cancelación manual del cliente.
--   • Cleanup de carrito abandonado (rev. 70).
--
-- Idempotente: solo afecta filas con status='active'.

CREATE OR REPLACE FUNCTION public.rpc_stock_reservation_release_by_conversation(
  p_conversation_id UUID
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  WITH upd AS (
    UPDATE public.stock_reservations
       SET status = 'released',
           released_at = NOW(),
           updated_at = NOW()
     WHERE conversation_id = p_conversation_id
       AND status = 'active'
     RETURNING 1
  )
  SELECT COUNT(*)::INT INTO v_count FROM upd;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.rpc_stock_reservation_release_by_conversation(UUID)
  TO authenticated, service_role;
