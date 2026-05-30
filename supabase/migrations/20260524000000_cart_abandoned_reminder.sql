-- =============================================================================
-- conversation_carts.abandoned_reminder_sent_at — idempotencia cron 24h
-- (Sem 7 F2 item 6.b / 2026-05-17).
--
-- Columna para que el cron `_send_cart_abandoned_reminders_if_due` no
-- envíe el mismo recordatorio 2 veces al mismo cliente, aún si el cron
-- corre cada minuto.
--
-- Patrón idéntico al de `orders.payment_reminder_sent_at` (rev. 103 F1):
--   NULL = no recordatorio enviado todavía
--   timestamp = ya se envió (skip futuro)
-- =============================================================================

ALTER TABLE public.conversation_carts
    ADD COLUMN IF NOT EXISTS abandoned_reminder_sent_at TIMESTAMPTZ;

COMMENT ON COLUMN public.conversation_carts.abandoned_reminder_sent_at IS
    'Idempotencia cron cart_abandoned_24h. NULL = pendiente; timestamp = enviado. '
    'Se setea cuando cron dispara HSM marketing cart_abandoned_24h_v1 a un '
    'cliente cuyo carrito tiene >24h sin actividad y status=open/abandoned. '
    'Patrón consistente con orders.payment_reminder_sent_at (F1).';

CREATE INDEX IF NOT EXISTS conversation_carts_abandoned_pending_idx
    ON public.conversation_carts (tenant_id, updated_at)
    WHERE abandoned_reminder_sent_at IS NULL
      AND status IN ('open', 'abandoned');
