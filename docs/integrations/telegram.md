# Integración Telegram Bot

Última actualización: 2026-04-20

---

## Estado

✅ **Implementado (fase operativa inicial)**

- Configuración por tenant en `notification_settings` (`channel='telegram'`).
- Trigger DB encola evento cuando una conversación pasa a `human_takeover`.
- AI Orchestrator consume cola Supabase Queues (`pgmq`) y despacha a Telegram.

---

## Propósito

Telegram como **canal interno del tenant** para alertas de operación.

Caso activo:
- Notificar al equipo del tenant cuando una conversación entra en `human_takeover`.

**Telegram NO es canal de atención al cliente.**
Atención cliente final: WhatsApp Cloud API.

---

## Arquitectura runtime

1. Cambio de estado en `conversations.status` a `human_takeover`.
2. Trigger SQL encola evento en `human_takeover_notifications` (Supabase Queues/pgmq).
3. Worker (`services/ai-orchestrator`) hace `dequeue`.
4. Se consulta `notification_settings` del tenant y se envía notificación Telegram.
5. ACK del mensaje en cola si se maneja correctamente.

---

## Configuración por tenant

Tabla: `notification_settings`

Valores de `config` para Telegram:
- `bot_token`
- `chat_id`

UI de configuración:
- `/dashboard/integrations` (sección Telegram)

---

## Canal Email (preparado)

El pipeline de eventos ya contempla canal `email` en `notification_settings`.
Actualmente está como placeholder no bloqueante en el worker (pendiente SMTP productivo).

---

## Reglas

- No enviar secretos ni PII sensible extensa por Telegram.
- Mantener mensajes orientados a acción operacional (resumen + link operativo).
- Todo envío se resuelve por tenant (`tenant_id`) sin configuración global compartida.
