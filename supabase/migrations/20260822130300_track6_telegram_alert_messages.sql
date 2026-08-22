-- =============================================================================
-- Track 6 / Telegram — telegram_alert_messages: persistencia de alertas con
-- inline keyboard (message_id) para editMessageReplyMarkup cross-canal
-- Fecha: 2026-08-22 · Origen: matriz Track 6 (core.telegram.org/bots/api —
-- fetch live 2026-08-22: answerCallbackQuery, editMessageReplyMarkup,
-- InlineKeyboardButton callback_data 1-64 bytes)
-- Tests: tests/dbharness/test_track6_telegram_alert_messages.py +
-- tests/test_telegram_webhook.py (callback_query)
--
-- Por qué existe: la alerta de human_takeover lleva un botón inline
-- "✅ Resolver". Al pulsarlo, el callback_query trae message_id y basta para
-- editar ese mensaje — pero resolver la conversación por OTRO canal (comando
-- /resolver en otro mensaje, o la consola Inbox) no tiene el message_id a la
-- mano. Esta tabla lo persiste al enviar la alerta (sendMessage lo devuelve)
-- y permite editar el markup de TODAS las alertas abiertas de la conversación
-- cuando se resuelve desde cualquier canal (anti doble-click / anti confusión
-- de operadores: el botón desaparece al quedar resuelta).
--
-- Seguridad: tabla de infra pura — patrón Track 9 M1-M4 (REVOKE a roles de
-- cliente, GRANT a service_role; RLS por tenant como defensa en profundidad).
-- El writer es el orchestrator (worker pgmq) y los lectores/editores son el
-- webhook Telegram y el endpoint de status de la consola, ambos con
-- service_role.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.telegram_alert_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  -- Sin FK a conversations a propósito: la retención legal puede purgar la
  -- conversación (G-8) y la alerta (ya enviada a Telegram) debe poder marcarse
  -- resuelta igual — un FK rompería el UPDATE (→ botón zombie).
  conversation_id UUID NOT NULL,
  -- chat_id como TEXT: los ids de supergrupo (-100XXXXXXXXXX) exceden INT4 y
  -- la config del tenant ya lo guarda como texto (notification_settings).
  chat_id         TEXT NOT NULL,
  message_id      BIGINT NOT NULL,
  alert_type      TEXT NOT NULL DEFAULT 'takeover',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- NULL = alerta abierta (botón activo). Se marca al resolver la conversación
  -- por cualquier canal (callback_query, /resolver, consola).
  resolved_at     TIMESTAMPTZ
);

-- Un mensaje de Telegram es único por (chat, message_id): la re-entrega del
-- evento pgmq no duplica la fila (ON CONFLICT DO NOTHING en el insert).
CREATE UNIQUE INDEX IF NOT EXISTS uq_telegram_alert_messages_msg
  ON public.telegram_alert_messages (chat_id, message_id);

-- Lookup de alertas abiertas al resolver (callback / comando / consola).
CREATE INDEX IF NOT EXISTS idx_telegram_alert_messages_conv_open
  ON public.telegram_alert_messages (conversation_id) WHERE resolved_at IS NULL;

ALTER TABLE public.telegram_alert_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant Isolation" ON public.telegram_alert_messages;
CREATE POLICY "Tenant Isolation" ON public.telegram_alert_messages
  FOR ALL USING (tenant_id = public.app_current_tenant())
  WITH CHECK (tenant_id = public.app_current_tenant());

-- Track 9 (patrón M1-M4): tabla de infra pura → nada a roles de cliente.
REVOKE ALL ON public.telegram_alert_messages FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.telegram_alert_messages TO service_role;

COMMENT ON TABLE public.telegram_alert_messages IS
'Track 6: message_id de las alertas Telegram con inline keyboard (takeover). Permite editMessageReplyMarkup al resolver la conversación desde cualquier canal (el callback_query trae message_id, pero /resolver y la consola no). resolved_at NULL = alerta abierta.';
