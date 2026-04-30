-- Rev. 79 — Cron job para marcar conversation_carts abandonados.
--
-- Contexto: conversation_carts.status soporta 'abandoned' en el CHECK pero
-- nunca se setea — los carritos en 'open'/'checkout' se quedan ahí
-- indefinidamente cuando el cliente desaparece sin completar pago.
--
-- Política (rev. 79):
--   • 7 días sin actividad (updated_at) → status='abandoned'.
--   • Solo afecta status IN ('open','checkout') — converted/cancelled/abandoned
--     se respetan.
--   • Idempotente: si un cart ya está abandoned, no se re-marca.
--   • La conversación NO se cierra; el contexto rev. 70 puede seguir
--     ofreciendo "retomar pedido".
--   • NO toca stock_reservations — esas siguen su propio TTL (35 min) y cron
--     fn_expire_stock_reservations cada 60s. La intención es marcar el cart,
--     no liberar stock que ya expiró por su lado.

CREATE OR REPLACE FUNCTION public.fn_expire_abandoned_carts()
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  WITH upd AS (
    UPDATE public.conversation_carts
       SET status = 'abandoned',
           updated_at = NOW()
     WHERE status IN ('open', 'checkout')
       AND updated_at < NOW() - INTERVAL '7 days'
     RETURNING 1
  )
  SELECT COUNT(*)::INT FROM upd;
$$;

GRANT EXECUTE ON FUNCTION public.fn_expire_abandoned_carts() TO service_role;

-- Schedule pg_cron: cada hora (sobra para una política de 7 días, evita
-- thundering herd a medianoche).
DO $$
BEGIN
  -- Limpiar schedule previo si existe (idempotente).
  PERFORM cron.unschedule(jobid)
  FROM cron.job
  WHERE jobname = 'expire_abandoned_carts';

  PERFORM cron.schedule(
    'expire_abandoned_carts',
    '17 * * * *',  -- minuto 17 cada hora (offset para no coincidir con otros jobs)
    $cron$ SELECT public.fn_expire_abandoned_carts(); $cron$
  );
EXCEPTION WHEN undefined_table THEN
  -- pg_cron no instalado: los environments locales/CI pueden no tenerlo.
  -- La función queda creada y puede invocarse manualmente.
  RAISE NOTICE 'pg_cron no disponible; fn_expire_abandoned_carts queda manual.';
END $$;
