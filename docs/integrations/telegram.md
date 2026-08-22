# Telegram — Canal interno de operación (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** (fetch live core.telegram.org/bots/api — Bot API 10.2 al 2026-07-14).

## Estado

**LIVE** — notificaciones outbound y webhook bidireccional con comandos operativos en producción. Significa: un tenant que configura su bot y chat en Integraciones recibe alertas de escalación (`human_takeover`) en Telegram y puede resolver conversaciones desde ahí mismo — por comando `/resolver`, **por el botón inline "✅ Resolver" de la propia alerta (Track 6)**, o desde la consola (y la alerta se actualiza en todos los caminos).

Telegram es **canal interno del tenant** (alertas de operación), NO canal de atención al cliente final — ese es WhatsApp. ADR-0021: `notification_settings` es la fuente única de verdad de canales de notificación.

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Outbound takeover (pgmq → Telegram) | `services/ai-orchestrator/notifications.py` (`dispatch_human_takeover_event`, `_send_telegram_notification`, `_takeover_reply_markup`, `_persist_alert_message`) | — |
| Outbound escalaciones del bot | `services/ai-orchestrator/telegram_notifications.py` (`notify_escalation_async:37`) | 148 |
| Webhook bidireccional (comandos + callback_query) | `services/api/routers/telegram_webhook.py` | — |
| Alertas desde el API + cierre de alertas | `services/api/lib/operator_alerts.py` (`notify_operator_telegram`, `resolve_takeover_alerts`) | — |
| Setup del webhook del tenant (Track 6, cierra M17) | `services/api/routers/integrations.py` (`POST /telegram/setup`) | — |
| Gestión de identidad (revocación) | `services/api/routers/integrations.py` (`DELETE /telegram/identity`) | — |
| Tabla de alertas con keyboard (Track 6) | migración `supabase/migrations/20260822130300_track6_telegram_alert_messages.sql` | — |
| Cola pgmq takeover | migración `supabase/migrations/20260420000003_human_takeover_notifications_queue.sql` | — |
| ADR fuente única notificaciones | `docs/adr/0021-notification-channels-unified-source.md` | — |

## Flujos implementados

### 1. Outbound: alerta de `human_takeover` (con inline keyboard — Track 6)

1. Una conversación pasa a `human_takeover` → trigger SQL encola el evento en la cola pgmq `human_takeover_notifications`.
2. El worker del orchestrator hace dequeue (`worker.py:1000`, RPC `dequeue_human_takeover_notifications`).
3. `dispatch_human_takeover_event` lee `notification_settings` del tenant (`channel='telegram'`, `enabled=true`), resuelve `bot_token` desde Vault y `chat_id` del config, y POSTea a `sendMessage` con **`parse_mode=HTML`** (Track 6 — el Markdown legacy rompía con contenido dinámico sin escapar: "can't parse entities"; todo valor dinámico pasa por `html.escape` y el fallback a texto plano se eliminó) e **inline keyboard** con el botón `✅ Resolver (devolver al bot)` (`callback_data="resolve:{conv_id}"` — 44 bytes, límite oficial 1-64).
4. Si el envío es OK, se **persiste `(tenant_id, conversation_id, chat_id, message_id)` en `telegram_alert_messages`** (`UNIQUE(chat_id, message_id)` — la re-entrega pgmq no duplica).
5. En el mismo envío se auto-vincula `(tenant_id, telegram, chat_id)` en `tenant_provider_identity` (`_register_telegram_identity`) — esa fila es la que luego da RBAC a los comandos y callbacks.
6. ACK de la cola solo si el envío se manejó correctamente; si no, el mensaje vuelve a visible para reintento.

`notify_escalation_async` (`telegram_notifications.py:37-148`) es el path de escalaciones del bot; usa la misma fuente (`notification_settings`), el mismo patrón Vault y el mismo sender HTML.

### 2. Inbound: webhook de comandos + callback_query

Receptor: `POST /api/v1/integrations/telegram/webhook` (`telegram_webhook.py`; mount en `main.py`).

1. **Auth**: Telegram envía `X-Telegram-Bot-Api-Secret-Token`; se compara en tiempo constante (`hmac.compare_digest`) contra `TELEGRAM_WEBHOOK_SECRET` global.
2. **`callback_query` (Track 6)**: el botón `✅ Resolver` ejecuta la MISMA acción de `/resolver` (`_cmd_resolver`, con el mismo RBAC chat_id→tenant) y luego:
   - `answerCallbackQuery` — **obligatorio** (sin él el botón queda "cargando" en el cliente; texto ≤200 chars, doc oficial);
   - cierre de alertas abiertas (abajo §3).
3. Se resuelve el tenant: primero `tenant_provider_identity`, y si no existe, **self-heal** contra `notification_settings` (exactamente 1 match o rechazo seguro).
4. Comandos (`_handle_command`):
   - `/resolver {conversation_id}` → restaura `bot_active` en la conversación (`_cmd_resolver`).
   - `/estado {conversation_id}` → responde el status actual (`_cmd_estado`).
   - Cualquier otro texto → ayuda con la lista de comandos.
5. Las respuestas salen por `_send_telegram_reply` (también reusado por el webhook de Aveonline para alertas internas) — **`parse_mode=HTML` con escape** (Track 6).
6. El RBAC es **chat_id = identidad del operador**: un comando solo muta conversaciones del tenant mapeado a ese chat.

### 3. Cierre de alertas cross-canal (Track 6 — anti doble-click / anti confusión)

Cuando la conversación vuelve a `bot_active` desde **cualquier** canal, `resolve_takeover_alerts` (`operator_alerts.py`) busca las filas abiertas de `telegram_alert_messages` para la conversación y por cada una llama `editMessageReplyMarkup` SIN `reply_markup` (la doc oficial: así se ELIMINA el teclado) y marca `resolved_at`. Los tres disparadores:

- el callback_query del propio botón (`telegram_webhook._handle_callback_query`);
- el comando `/resolver` (`_cmd_resolver`);
- la consola Inbox (`conversations.update_conversation_status` → helper `_close_takeover_alerts_if_resolved`).

Resultado: un segundo operador nunca pisa al primero — el botón desaparece para todo el grupo al quedar resuelta. Todo el path es best-effort (nunca rompe el resolve).

## Config por tenant vs global

### Por tenant — `notification_settings` (`channel='telegram'`)

```json
"config": { "bot_token": "<secret_id Vault>", "chat_id": "123456789" }
```

- `bot_token`: cifrado en Vault (se resuelve con `resolve_secret`).
- `chat_id`: en claro en config (no es secreto; es el identificador RBAC).
- UI de configuración: Ajustes → Integraciones → Telegram. Revocación de identidad operador: `DELETE /api/v1/integrations/telegram/identity` [owner/manager].

### Global (env vars)

| Var | Valor | Servicio | Qué controla |
|---|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | `sync:false` | api | Secret compartido con Telegram en `setWebhook`; autentica todo el inbound (`render.yaml:259-262`, `.env.example`) |

Un solo secret global para todos los tenants (el aislamiento lo da el mapping chat_id→tenant, no el secret). Punto de extensión documentado: secret per-tenant (abajo §"Diseñado para el futuro").

## Seguridad

- **Secret token** verificado en tiempo constante en cada POST (comandos y callbacks).
- **RBAC estricto por chat_id**: comandos y callbacks solo operan sobre el tenant vinculado; ambigüedad (mismo chat en 2 tenants) = rechazo + log estructurado.
- **Self-heal auditado**: la auto-vinculación se registra en `tenant_provider_identity` con `metadata.source = 'webhook_self_heal'`.
- **`telegram_alert_messages` es tabla de infra** (patrón Track 9): `REVOKE ALL` a `anon`/`authenticated`, `GRANT` a `service_role`, RLS por tenant — una fila forjada haría editar mensajes arbitrarios, así que la escritura es solo de servicios. Ataques cubiertos en `tests/dbharness/test_track6_telegram_alert_messages.py`.
- No se envían secretos ni PII extensa por Telegram; mensajes orientados a acción (resumen + link al Inbox).
- `callback_data` nunca contiene secretos — solo `resolve:{conv_id}` (el RBAC lo da el chat, no el dato).

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| API de Telegram cae en outbound | El evento pgmq no se ACKea → reintento por visibility timeout; no se pierde la alerta |
| `bot_token` inválido/revocado | Log warning; el evento queda para revisión; la escalación en Inbox no depende de Telegram |
| Webhook inbound con secret malo | 401 genérico (`Token inválido`, sin leak de detalle); 503 si `TELEGRAM_WEBHOOK_SECRET` no está configurado |
| Comando/callback de chat no vinculado | Rechazo seguro + log; self-heal lo resuelve en el próximo intento si el tenant ya configuró el chat |
| Tenant sin canal telegram configurado | Skip explícito con log — no rompe el flujo de takeover |
| `telegram_alert_messages` inaccesible | El resolve funciona igual (cierre de alertas es best-effort, log `[OP_ALERT]`) |
| Error 400 de formato (HTML) | Permanente: no re-encolar (con `html.escape` no debería ocurrir; el fallback a texto plano se eliminó con la migración a HTML) |

## Operación

- **Alta del webhook (Track 6 — automática, cierra M17)**: `POST /api/v1/integrations/telegram/setup` [owner/manager] ejecuta la cadena oficial `getMe` → `setWebhook(url, secret_token, allowed_updates=["message","callback_query"], drop_pending_updates=true)` → `setMyCommands(/resolver /estado /ayuda)` → `getWebhookInfo` y devuelve el estado. La consola lo llama tras guardar token + chat_id.
- **Contingencia manual** (si el endpoint falla): `setWebhook` con curl (mismo contrato de URL + secret).
- **Monitoreo disponible**: logs `[TG_WH]` (comandos, callbacks, self-heal, rechazos), `[TG_ESCALATION]`, `[OP_ALERT]` (cierre de alertas) y `[TG_SETUP]` en Render Dashboard.
- **Dependencia de plataforma**: el valor de `TELEGRAM_WEBHOOK_SECRET` en Render debe coincidir con el usado en cada `setWebhook`; rotarlo implica re-registrar los webhooks de todos los bots (con el endpoint setup es una llamada por tenant).

## Alta de un bot (procedimiento verificado E2E en STG 2026-08-19/20)

Un bot por ambiente/tenant (la doc oficial de Telegram recomienda crear bots separados para pruebas vía @BotFather — [Bot Features](https://core.telegram.org/bots/features)). **Nunca** va a env vars globales: el token es per-tenant en Vault (`.env.example` — "la global nunca se lee").

1. **Crear el bot:** @BotFather → `/newbot` → nombre visible → username terminado en `bot` (**inmutable**). BotFather entrega el `token`.
2. **Grupo de operadores:** crear el grupo y **agregar el bot**. Las notificaciones van a grupo, no a chat personal.
3. **Obtener el `chat_id` del grupo (SIEMPRE negativo):** dentro del grupo enviar `/start@<bot_username>` y leer `getUpdates` → `message.chat.id`. Privados son positivos y NO sirven.
4. **Alta en el panel del tenant:** Ajustes → Integraciones → Telegram → Bot Token + Chat ID (con el signo `-`) → Conectar. El token queda en Vault.
5. **Webhook:** automático con el botón/endpoint de setup (Track 6) apuntando al ambiente correspondiente (PRD: `https://konvi-api.onrender.com/…`; STG: la URL ngrok del api, `make -C .local print-urls`).
6. **Verificación:** provocar una escalación → el mensaje llega al grupo con el botón `✅ Resolver`; pulsarlo devuelve la conversación al bot y el botón desaparece.

> STG quedó con: bot `@konvi_stg_bot` + grupo `Konvi STG Operadores` — registrado aquí para re-armado del ambiente (los secretos viven en el Vault local, nunca en docs).

## Diseñado para el futuro (puntos de extensión, con gates) — Track 6

| Ítem | Doc oficial | Gate de adopción |
|---|---|---|
| **Mensajes efímeros** (Bot API 10.2, 2026-07-14): `sendMessage(receiver_user_id=…)` hace visible la respuesta SOLO para quien ejecuta el comando — la PII de `/estado` (teléfono del cliente) dejaría de quedar visible para TODO el grupo | [Bot API 10.2 changelog](https://core.telegram.org/bots/api#july-14-2026) (`is_ephemeral`, `receiver_user`, editEphemeralMessage*) | Verificar en STG que el grupo STG acepta efímeros (feature recién liberada; requiere clientes actualizados). Cuando se adopte: `/estado` efímero por defecto |
| **`message_thread_id` para grupos-foro**: si un tenant opera con un supergrupo-foro, las alertas podrían abrir un topic por conversación (orden por caso) | [sendMessage](https://core.telegram.org/bots/api#sendmessage) | Primer tenant con grupo-foro |
| **`TELEGRAM_WEBHOOK_SECRET` per-tenant**: hoy global único (la rotación implica re-registrar todos los bots); el setup endpoint ya aísla el punto de cambio | [setWebhook secret_token](https://core.telegram.org/bots/api#setwebhook) (1-256 chars, A-Za-z0-9_-) | Cuando haya >N tenants con bots propios o una rotación de emergencia |
| Botones adicionales en la alerta (`/estado` como callback, cerrar conversación) | mismo handler callback_query (`data` namespaced) | Cuando operación lo pida — el patrón ya está: callback_data + RBAC + answer + edit |
| Rich Messages (Bot API 10.1/10.2: bloques estructurados) | [changelog](https://core.telegram.org/bots/api) | NO adoptar aún — recién liberado, sin necesidad de negocio; HTML cubre el formato actual |

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| ~~M17~~ | ~~Medio~~ | ✅ **CERRADO 2026-08-22 (Track 6)**: `POST /api/v1/integrations/telegram/setup` registra el webhook desde la UI (getMe→setWebhook→setMyCommands→getWebhookInfo) — el paso manual con curl queda como contingencia |
| — | Bajo | Secret de webhook global único (no per-tenant); rotación = re-registro masivo. Mitigado por RBAC chat_id→tenant y por el setup endpoint (punto de extensión documentado arriba) |

## Referencias oficiales (fetcheadas 2026-08-22)

- Telegram Bot API: [setWebhook](https://core.telegram.org/bots/api#setwebhook) (secret_token, allowed_updates) · [answerCallbackQuery](https://core.telegram.org/bots/api#answercallbackquery) (obligatorio, texto ≤200) · [editMessageReplyMarkup](https://core.telegram.org/bots/api#editmessagereplymarkup) (sin reply_markup = elimina el teclado) · [InlineKeyboardButton](https://core.telegram.org/bots/api#inlinekeyboardbutton) (callback_data 1-64 bytes) · [CallbackQuery](https://core.telegram.org/bots/api#callbackquery) · [setMyCommands](https://core.telegram.org/bots/api#setmycommands) · [Bot API 10.2 — ephemeral messages](https://core.telegram.org/bots/api#july-14-2026)
- Dossier histórico: `docs/_archive/research/telegram-dossier-2026-05-05.md`.

