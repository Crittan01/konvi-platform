# Telegram — Canal interno de operación (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

## Estado

**LIVE** — notificaciones outbound y webhook bidireccional con comandos operativos en producción. Significa: un tenant que configura su bot y chat en Integraciones recibe alertas de escalación (`human_takeover`) en Telegram y puede resolver conversaciones desde ahí mismo.

Telegram es **canal interno del tenant** (alertas de operación), NO canal de atención al cliente final — ese es WhatsApp. ADR-0021: `notification_settings` es la fuente única de verdad de canales de notificación.

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Outbound takeover (pgmq → Telegram) | `services/ai-orchestrator/notifications.py` (`dispatch_human_takeover_event:379`, `_send_telegram_notification:96`) | 425 |
| Outbound escalaciones del bot | `services/ai-orchestrator/telegram_notifications.py` (`notify_escalation_async:37`) | 148 |
| Webhook bidireccional (comandos) | `services/api/routers/telegram_webhook.py` | 360 |
| Gestión de identidad (revocación) | `services/api/routers/integrations.py` (`DELETE /telegram/identity:407`) | — |
| Cola pgmq takeover | migración `supabase/migrations/20260420000003_human_takeover_notifications_queue.sql` | — |
| ADR fuente única notificaciones | `docs/adr/0021-notification-channels-unified-source.md` | — |

## Flujos implementados

### 1. Outbound: alerta de `human_takeover`

1. Una conversación pasa a `human_takeover` → trigger SQL encola el evento en la cola pgmq `human_takeover_notifications`.
2. El worker del orchestrator hace dequeue (`worker.py:1000`, RPC `dequeue_human_takeover_notifications`).
3. `dispatch_human_takeover_event` lee `notification_settings` del tenant (`channel='telegram'`, `enabled=true`), resuelve `bot_token` desde Vault y `chat_id` del config, y POSTea a `https://api.telegram.org/bot{token}/sendMessage` (`notifications.py:96-156`, con fallback sin markdown si el parse falla).
4. En el mismo envío se auto-vincula `(tenant_id, telegram, chat_id)` en `tenant_provider_identity` (`_register_telegram_identity:34-75`) — esa fila es la que luego da RBAC a los comandos.
5. ACK de la cola solo si el envío se manejó correctamente; si no, el mensaje vuelve a visible para reintento.

`notify_escalation_async` (`telegram_notifications.py:37-148`) es el path de escalaciones del bot; usa la misma fuente (`notification_settings`) y el mismo patrón Vault.

### 2. Inbound: webhook de comandos

Receptor: `POST /api/v1/integrations/telegram/webhook` (`telegram_webhook.py:61`; mount en `main.py:295`).

1. **Auth**: Telegram envía `X-Telegram-Bot-Api-Secret-Token`; se compara en tiempo constante (`hmac.compare_digest`) contra `TELEGRAM_WEBHOOK_SECRET` global (`telegram_webhook.py:64-75`).
2. Se extrae `chat_id` + autor (audit) y se resuelve el tenant: primero `tenant_provider_identity` (`resolve_tenant_id`), y si no existe, **self-heal**: se busca `notification_settings` cuyo `config.chat_id` coincida; con **exactamente 1** match se registra la identidad y se autoriza; con 0 o >1 (ambiguo) → rechazo seguro (`telegram_webhook.py:113-199`).
3. Comandos (`_handle_command:212`):
   - `/resolver {conversation_id}` → restaura `bot_active` en la conversación (`_cmd_resolver:236`).
   - `/estado {conversation_id}` → responde el status actual (`_cmd_estado:277`).
   - Cualquier otro texto → ayuda con la lista de comandos.
4. La respuesta sale por `_send_telegram_reply` (también reusado por el webhook de Aveonline para alertas internas, `aveonline_webhook.py:420-421`).
5. El RBAC es **chat_id = identidad del operador**: un comando solo muta conversaciones del tenant mapeado a ese chat; el comentario en `:104-109` documenta el caso cross-tenant que esto cerró.

## Config por tenant vs global

### Por tenant — `notification_settings` (`channel='telegram'`)

```json
"config": { "bot_token": "<secret_id Vault>", "chat_id": "123456789" }
```

- `bot_token`: cifrado en Vault (se resuelve con `resolve_secret`).
- `chat_id`: en claro en config (no es secreto; es el identificador RBAC).
- UI de configuración: Ajustes → Integraciones → Telegram. Revocación de identidad operador: `DELETE /api/v1/integrations/telegram/identity` [owner/manager] (`integrations.py:407-461`).

### Global (env vars)

| Var | Valor | Servicio | Qué controla |
|---|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | `sync:false` | api | Secret compartido con Telegram en `setWebhook`; autentica todo el inbound (`render.yaml:259-262`, `.env.example:99-104`) |

Un solo secret global para todos los tenants (el aislamiento lo da el mapping chat_id→tenant, no el secret).

## Seguridad

- **Secret token** verificado en tiempo constante en cada POST (`telegram_webhook.py:75`).
- **RBAC estricto por chat_id**: comandos solo operan sobre el tenant vinculado; ambigüedad (mismo chat en 2 tenants) = rechazo + log estructurado (`:180-186`).
- **Self-heal auditado**: la auto-vinculación se registra en `tenant_provider_identity` con `metadata.source = 'webhook_self_heal'` (`:194`).
- No se envían secretos ni PII extensa por Telegram; mensajes orientados a acción (resumen + link al Inbox).

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| API de Telegram cae en outbound | El evento pgmq no se ACKea → reintento por visibility timeout; no se pierde la alerta |
| `bot_token` inválido/revocado | Log warning ("habilitado pero incompleto" / HTTP error de Telegram); el evento queda para revisión; la escalación en Inbox no depende de Telegram |
| Webhook inbound con secret malo | 401 genérico (`Token inválido`, sin leak de detalle); 503 si `TELEGRAM_WEBHOOK_SECRET` no está configurado (`telegram_webhook.py:70-77`) |
| Comando de chat no vinculado | Rechazo seguro + log; self-heal lo resuelve en el próximo intento si el tenant ya configuró el chat |
| Tenant sin canal telegram configurado | Skip explícito con log (`[TG_ESCALATION] ... sin canal telegram`) — no rompe el flujo de takeover |

## Operación

- **Manual por tenant (M17)**: `setWebhook` no es automático. Tras crear el bot con BotFather y configurarlo en Integraciones, hay que registrar el webhook a mano (una vez por bot):

  ```bash
  curl "https://api.telegram.org/bot{TOKEN}/setWebhook" \
    -d "url=https://konvi-api.onrender.com/api/v1/integrations/telegram/webhook" \
    -d "secret_token={TELEGRAM_WEBHOOK_SECRET}"
  ```

  (documentado en `telegram_webhook.py:28-33` y `.env.example:99-104`).
- **Monitoreo disponible**: logs `[TG_WH]` (comandos, self-heal, rechazos) y `[TG_ESCALATION]` en Render Dashboard.
- **Dependencia de plataforma**: el valor de `TELEGRAM_WEBHOOK_SECRET` en Render debe coincidir con el usado en cada `setWebhook`; rotarlo implica re-registrar los webhooks de todos los bots.

## Alta de un bot (procedimiento verificado E2E en STG 2026-08-19/20)

Un bot por ambiente/tenant (la doc oficial de Telegram recomienda crear bots separados para pruebas vía @BotFather — [Bot Features](https://core.telegram.org/bots/features)). **Nunca** va a env vars globales: el token es per-tenant en Vault (`.env.example:230` — "la global nunca se lee").

1. **Crear el bot:** @BotFather → `/newbot` → nombre visible (ej. `Konvi STG`) → username terminado en `bot` (ej. `konvi_stg_bot`; **inmutable** — elegir bien). BotFather entrega el `token` (`123456:AAH…`).
2. **Grupo de operadores:** crear el grupo (ej. "Konvi STG Operadores") y **agregar el bot**. Las notificaciones van a grupo, no a chat personal — el formulario del panel exige chat_id de grupo (`pattern="-\d+"`).
3. **Obtener el `chat_id` del grupo (SIEMPRE negativo):** dentro del grupo enviar `/start@<bot_username>` — con el *privacy mode* por defecto el bot solo ve en grupos los comandos dirigidos a él; un mensaje normal no le llega. Luego leer `https://api.telegram.org/bot<TOKEN>/getUpdates` → `message.chat.id` (formato `-XXXXXXXXXX`; supergrupos `-100XXXXXXXXXX`). Privados son positivos y NO sirven para este campo.
4. **Alta en el panel del tenant:** Ajustes → Integraciones → Telegram → pegar **Bot Token** + **Chat ID del grupo** (con el signo `-`) → Conectar. El token queda en Vault (`notification_settings.config.bot_token_secret_id`).
5. **Webhook (si se usan comandos inbound):** `setWebhook` manual por bot (comando de arriba) apuntando al ambiente correspondiente (PRD: `https://konvi-api.onrender.com/…`; STG: la URL ngrok del api, `make -C .local print-urls`).
6. **Verificación:** provocar una escalación/notificación del tenant → el mensaje llega al grupo. En STG (2026-08-20) verificado con bot `konvi_stg_bot` + grupo `Konvi STG Operadores` (chat_id `-5381900925`).

> STG quedó con: bot `@konvi_stg_bot` + grupo `Konvi STG Operadores` — registrado aquí para re-armado del ambiente (los secretos viven en el Vault local, nunca en docs).

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| M17 | Medio | `setWebhook` manual por tenant — onboarding Telegram requiere paso operador fuera de la UI |
| — | Bajo | Secret de webhook global único (no per-tenant); rotación = re-registro masivo. Mitigado por RBAC chat_id→tenant |

## Referencias oficiales

- Telegram Bot API (`setWebhook`, `sendMessage`, header `X-Telegram-Bot-Api-Secret-Token`): https://core.telegram.org/bots/api — dossier histórico en `docs/_archive/research/telegram-dossier-2026-05-05.md`.
