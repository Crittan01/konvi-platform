-- Rev. 109 backlog #3 — Channel Registry pluggable (Plan I.3).
--
-- PROBLEMA QUE RESUELVE:
-- ─────────────────────
-- Hoy el sistema asume implícitamente WhatsApp como único canal (campos
-- como conversations.customer_phone, connector-whatsapp dedicado, etc.).
-- Para soportar futuros canales (Messenger, Instagram Direct, TikTok Shop,
-- Web Storefront chat, SMS, Telegram público), necesitamos:
--   1. Marcar explícitamente el canal de cada conversación.
--   2. Que el orchestrator pueda ramificar lógica per-canal (limit chars,
--      formato markdown WA vs HTML web, compliance Meta vs IG, etc.).
--
-- DISEÑO:
-- ───────
-- Agregar `conversations.channel TEXT NOT NULL DEFAULT 'whatsapp'`.
-- Default 'whatsapp' preserva comportamiento actual: todas las
-- conversaciones existentes y nuevas (sin set explícito) siguen siendo
-- WhatsApp. Cuando un canal nuevo se active, su connector setea el campo.
--
-- VALORES CANÓNICOS (case-sensitive, ASCII lowercase):
--   'whatsapp'    — Meta WhatsApp Cloud API (canal actual)
--   'meli'        — MercadoLibre Messages
--   'telegram'    — Telegram bot (canal interno operadores)
--   'web'         — Storefront chat embebido (futuro)
--   'messenger'   — Meta Messenger Platform (futuro)
--   'instagram'   — Instagram Direct (futuro)
--   'sms'         — SMS (futuro)
--
-- Channel Registry pluggable lee este campo + auto-discover adapter
-- registrado para responder coherentemente.

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp';

-- Index para queries multi-canal: "todas las conversaciones de tenant X
-- en canal web hoy".
CREATE INDEX IF NOT EXISTS conversations_tenant_channel_idx
  ON conversations (tenant_id, channel);

COMMENT ON COLUMN conversations.channel IS
  'Canal de origen. Default ''whatsapp''. Valores canónicos: whatsapp, '
  'meli, telegram, web, messenger, instagram, sms. Channel Registry '
  'pluggable usa este valor para ramificar adapter.';
