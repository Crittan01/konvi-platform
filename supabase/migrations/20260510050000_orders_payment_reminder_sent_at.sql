-- =============================================================================
-- Rev. 103 — F1 — Recordatorio de pago dentro de la CSW (24h Meta).
--
-- Contexto: link Wompi vence a los 30 min. Si el cliente está dentro de la
-- ventana de 24h de WhatsApp (CSW abierta), el bot puede enviarle un
-- recordatorio free-form gratis para evitar abandono. Sin esta columna no
-- hay forma de prevenir duplicados (cron corre cada N segundos).
--
-- Decisión: marcar idempotencia en orders.payment_reminder_sent_at.
-- Tras enviarlo, NO se reenvía aunque el cron corra otra vez. Si el link
-- expira (35min) la orden pasa a cancelled por el flujo existente.
-- =============================================================================

ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS payment_reminder_sent_at TIMESTAMPTZ;

COMMENT ON COLUMN public.orders.payment_reminder_sent_at IS
    'Rev. 103 — timestamp del recordatorio de pago enviado por WhatsApp '
    '(solo si CSW abierta). Idempotencia: NULL = no enviado, set = enviado.';
