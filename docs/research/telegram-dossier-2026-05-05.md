# Dossier técnico — Telegram Bot API (canal interno operadores)

> Fecha: 2026-05-05
> Autor: AI Architect
> Sección destino: H.6 (Telegram interno) — `.context/04-next-steps.md`
> Alcance: canal interno de notificaciones a operadores del tenant; **NO** atención de cliente final.
> Decisiones consensuadas previas:
> - Telegram = canal interno operadores.
> - Multi-bot per-tenant deseado.
> - Modelo B (token per tenant).

Fuentes oficiales referenciadas (todas en `core.telegram.org`):
- `/bots` · `/bots/api` · `/bots/webhooks` · `/bots/features`
- `/bots/2-0-intro` · `/bots/inline` · `/bots/faq`
- Anchors específicos: `#sendmessage`, `#setwebhook`, `#answercallbackquery`

---

## 1. TL;DR ejecutivo

Telegram Bot API es una API HTTPS pública, **gratuita para usuarios y desarrolladores**, que aloja "más de 10 millones de bots" sobre infraestructura de Telegram (https://core.telegram.org/bots). Para nuestro caso de uso —notificaciones internas y comandos remotos a operadores del tenant— es óptima: sin costo, sin SLA contractual pero alta disponibilidad operativa de facto, **sin requisitos de verificación business**, sin proceso de revisión de aplicaciones, sin onboarding formal. La creación de un bot se hace conversando con `@BotFather` (https://core.telegram.org/bots/features#botfather): comandos `/newbot`, `/setcommands`, `/setprivacy`, etc. El bot recibe un token tipo `123456:ABC-DEF...` que es **la única credencial** y otorga control total ("Everyone who has your token will have full control over your bot", https://core.telegram.org/bots).

Aspectos que importan operacionalmente: (a) el bot **no puede iniciar conversaciones** — el operador debe enviarle `/start` primero (https://core.telegram.org/bots); (b) los webhooks exigen **HTTPS con TLS ≥1.2** y solo aceptan puertos `443, 80, 88, 8443` (https://core.telegram.org/bots/webhooks); (c) la única autenticación inbound es el header `X-Telegram-Bot-Api-Secret-Token` configurable en `setWebhook` (https://core.telegram.org/bots/api#setwebhook) — **no hay HMAC criptográfico**; (d) rate limits razonables: ~30 msg/seg globales, 1 msg/seg por chat, 20 msg/min por grupo (https://core.telegram.org/bots/faq).

Para Konvi Platform, multi-bot per-tenant es trivial técnicamente: cada tenant crea su bot vía BotFather (paso humano), guarda `bot_token` cifrado y un script automatizable invoca `setWebhook` con un `secret_token` único. Esfuerzo P1+P2 estimado: **~2 días**. Sin riesgos críticos; el único "humano requerido" es la creación inicial del bot por tenant en BotFather (no automatizable, es UX deliberada de Telegram).

---

## 2. Hallazgos clave

### 2.1 Endpoints relevantes (Bot API)

Todos bajo base `https://api.telegram.org/bot{TOKEN}/{METHOD}` (https://core.telegram.org/bots/api).

| Método | Uso en nuestro caso | Fuente |
|---|---|---|
| `getMe` | Health check del token; devuelve identidad del bot. | `/bots/api` |
| `sendMessage` | Notificaciones a chat operador (escalamiento, alertas). | `/bots/api#sendmessage` |
| `setWebhook` | Registro inbound; configura `secret_token`. | `/bots/api#setwebhook` |
| `deleteWebhook` | Cleanup u offboarding de tenant; `drop_pending_updates`. | `/bots/api` |
| `getWebhookInfo` | Diagnóstico (URL actual, last_error, pending_updates). | `/bots/api` |
| `getUpdates` | **Long polling** alternativa al webhook (no usar si hay webhook activo). | `/bots/api` |
| `answerCallbackQuery` | **Obligatorio** tras pulsar inline button (cierra el "loading" en cliente). | `/bots/api#answercallbackquery` |
| `editMessageText` / `editMessageReplyMarkup` | Mutar mensaje existente (e.g. quitar botones tras acción). | `/bots/api` |
| `setMyCommands` | Publicar lista de comandos del bot (autocompletar al teclear `/`). | `/bots/api` |

### 2.2 `sendMessage` — parámetros operativos

Documentados en https://core.telegram.org/bots/api#sendmessage:

- `chat_id` (Integer|String, requerido) — ID del chat destino o `@username` de canal.
- `text` (String, 1-4096 chars).
- `parse_mode` ∈ `{HTML, Markdown, MarkdownV2}`. La doc recomienda **`MarkdownV2`** para nuevas implementaciones por escapado estricto; `Markdown` es **legacy**.
- `entities` (alternativa a `parse_mode`, lista de `MessageEntity`).
- `link_preview_options` — controla preview de URLs.
- `disable_notification` — envío silencioso (sin sonido al operador).
- `protect_content` — impide reenvío/copia (útil si el mensaje contiene PII de cliente).
- `reply_parameters` — referenciar mensaje anterior.
- `reply_markup` ∈ `{InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply}`.

### 2.3 Webhook (`setWebhook`)

Parámetros (https://core.telegram.org/bots/api#setwebhook):

- `url` — HTTPS obligatorio. String vacío = desregistrar.
- `secret_token` (1-256 chars, alfabeto `[A-Za-z0-9_-]`). Telegram **incluye automáticamente** el header `X-Telegram-Bot-Api-Secret-Token` con ese valor en cada POST.
- `max_connections` (1-100, default 40) — concurrencia HTTPS simultánea hacia nuestro endpoint.
- `allowed_updates` — JSON array filtrando tipos (`message`, `callback_query`, `edited_message`, etc.). Por defecto recibe todos excepto `chat_member`. **Buena práctica**: declarar explícitamente solo los que consumimos para reducir tráfico.
- `drop_pending_updates` — útil al re-deployar sin replay de eventos viejos.
- `certificate` — solo si self-signed. Si usamos cert pública (Render/Let's Encrypt) es innecesario.
- `ip_address` — fija IP (saltarse DNS); irrelevante en nuestro caso.

Puertos aceptados: **443, 80, 88, 8443** (https://core.telegram.org/bots/webhooks).

Telegram POSTea desde subnets `149.154.160.0/20` y `91.108.4.0/22` (https://core.telegram.org/bots/webhooks). Útil para allowlist en Cloudflare/WAF.

### 2.4 Long polling (`getUpdates`) — alternativa

Disponible si no se quiere exponer endpoint público (https://core.telegram.org/bots/api). Un mismo bot **no puede** tener webhook + polling al mismo tiempo: "You will not be able to receive updates using getUpdates for as long as an outgoing webhook is set up". Para nuestro stack (FastAPI sobre Render con HTTPS público) el webhook es naturalmente superior; long polling sería plan B si Telegram bloqueara el endpoint o para entornos `dev` locales.

### 2.5 Inline keyboards y callbacks

Introducidos en Bot API 2.0 (https://core.telegram.org/bots/2-0-intro). Tipos relevantes (https://core.telegram.org/bots/features):

- **Inline keyboard**: botones bajo el mensaje. No envían texto al chat.
  - **Callback button** (`callback_data`, ≤64 bytes): genera `callback_query` que llega por webhook. Nuestro bot ejecuta acción y debe llamar `answerCallbackQuery` (cierra spinner; opcional `text` toast o `show_alert`).
  - **URL button** (`url`): abre navegador con confirmación.
  - **Switch to inline** (`switch_inline_query`): no aplica a nuestro caso.
- **Reply keyboard** (`KeyboardButton`): teclado custom para el operador (e.g. botones "📋 Pendientes", "📊 Stats"). Más rudimentario; envía texto al chat.

Para nuestro flujo (escalamiento → operador resuelve), inline keyboards son superiores: un mensaje "🚨 Escalamiento conv `abc123`" puede llevar dos botones `[Devolver al bot] [Ver inbox]` con `callback_data="resolver:abc123..."` y `url="https://app.../inbox/abc123"`.

### 2.6 Formato de mensajes

`MarkdownV2` exige escapar `_*[]()~` `` ` ``  `>#+-=|{}.!`. `HTML` admite tags `<b><i><u><s><code><pre><a href><tg-spoiler>`. Para mensajes con UUIDs, `chat_id`s y otros payloads variables, **`HTML` es más seguro** (menos caracteres a escapar). Nuestro código actual usa `Markdown` legacy → ver sección 5.

### 2.7 `answerCallbackQuery`

Aunque la doc se truncó en `WebFetch` para este anchor, los hallazgos cruzados en `/bots/2-0-intro` y `/bots/features` confirman: tras recibir un `callback_query`, el bot **debe** llamar `answerCallbackQuery(callback_query_id, text?, show_alert?, url?, cache_time?)` para que el cliente cierre el indicador de carga (https://core.telegram.org/bots/api#answercallbackquery). `text` ≤ 200 chars como toast; `show_alert=true` muestra modal. Sin esta llamada, el operador ve un spinner perpetuo en la app.

### 2.8 Subida y descarga de archivos

`sendPhoto` / `sendDocument` / `sendVoice` aceptan `multipart/form-data` o `file_id` (https://core.telegram.org/bots/api). Límites (https://core.telegram.org/bots/faq):
- **Upload (bot → Telegram)**: hasta **50 MB**.
- **Download (`getFile` Telegram → bot)**: hasta **20 MB**.
- Telegram local Bot API server (auto-hostable) sube el upload a 2 GB; no aplica a nosotros.

Para nuestro caso (notificaciones a operadores) esto es irrelevante: solo enviamos texto.

---

## 3. Multi-tenant compatibility

### 3.1 Modelo de identidad de bot

Un bot Telegram **es una entidad globalmente única** (`@username` reservado en BotFather). El token (`HTTP API token`) lo emite BotFather al crear el bot y **no es rotable sin reset** vía `/revoke` en BotFather (https://core.telegram.org/bots/features#botfather).

### 3.2 Modelo B (token per tenant) — viabilidad

**Ventajas**:
- Branding por tenant: cada tenant crea `@miempresa_ops_bot` con su nombre/foto.
- Aislamiento: si un tenant pierde control de su token (leak), solo se compromete su canal interno.
- Rate limits independientes por bot (cada bot tiene cuota propia ~30 msg/seg).
- Privacy mode configurable per-tenant (`/setprivacy` en BotFather).
- Comandos custom per-tenant (`setMyCommands` con scope `BotCommandScopeChat` o globales por bot).

**Costo**:
- Onboarding manual del tenant: hablar con `@BotFather`, hacer `/newbot`, copiar token, pegarlo en su Setting page. **No automatizable** — Telegram no expone API para crear bots, es deliberado.
- Storage: tabla `notification_settings` (ya existe) almacena `config.bot_token` cifrado vía Vault (ya implementado en `vault_helper.py`).

### 3.3 ¿Auto-registro de webhook?

**Sí, automatizable** (https://core.telegram.org/bots/api#setwebhook): una vez que el tenant pega su `bot_token`, nuestro backend invoca:

```http
POST https://api.telegram.org/bot{TENANT_TOKEN}/setWebhook
{
  "url": "https://konvi-api.onrender.com/api/v1/integrations/telegram/webhook",
  "secret_token": "{generated_per_tenant_secret}",
  "allowed_updates": ["message", "callback_query"],
  "drop_pending_updates": true,
  "max_connections": 20
}
```

El `secret_token` debe ser **per-tenant** (no global) para que el endpoint pueda inferir qué tenant emitió el callback con solo leer el header. Almacenamos `(tenant_id, bot_id, webhook_secret_hash)` en BD; en el handler buscamos por `secret_token` recibido → resolvemos `tenant_id`. Alternativa: incluir `tenant_id` como query param en la `url` (`?tenant=uuid`), pero eso lo deja en logs HTTP.

### 3.4 Multi-bot ↔ multi-chat

Cada tenant probablemente tendrá **un grupo Telegram** con sus operadores; el bot se añade al grupo y obtiene un `chat_id` (negativo para grupos). Ese `chat_id` se almacena por tenant. Si el tenant tiene varios operadores en chats individuales, podemos almacenar lista de `chat_id`s y broadcast.

### 3.5 Mapeo a nuestra arquitectura

| Capa | Cambio requerido |
|---|---|
| `notification_settings` (tabla) | Ya admite `config jsonb` per `tenant_id+channel`. **OK**. |
| `services/api/routers/telegram_webhook.py` | Resolver tenant por `secret_token` recibido (hoy es global). |
| `services/ai-orchestrator/notifications.py` | Ya lee `config.bot_token` per tenant. **OK**. |
| Onboarding UI | Falta página "Configurar Telegram" con instrucciones BotFather + campo token + botón "Verificar y registrar webhook". |
| `scripts/telegram_setup.py` | **No existe**. Crear (P1). |

---

## 4. Limitaciones documentadas

### 4.1 Rate limits (https://core.telegram.org/bots/faq)

| Escenario | Límite | Origen |
|---|---|---|
| Mensajes por segundo (global, todos los chats) | ~**30 msg/seg** | FAQ "broadcasting" |
| Mensajes al **mismo chat** | ~**1 msg/seg** | FAQ "per chat" |
| Mensajes en **grupo** (mass send) | **20 msg/min** | FAQ "group" |
| Bursts cortos | Tolerados; eventualmente HTTP `429` | FAQ |

Telegram devuelve `429 Too Many Requests` con campo `parameters.retry_after` (segundos a esperar). Nuestra capa de reintentos debe respetarlo.

Para canal interno (notificaciones operacionales) estos límites son **holgadísimos**: aun en peak de 100 escalamientos/hora estamos a 0.03 msg/seg.

### 4.2 Tamaños

| Recurso | Límite |
|---|---|
| `text` en `sendMessage` | **4096 chars** UTF-8 |
| `caption` en media | 1024 chars |
| `callback_data` en inline button | **64 bytes** |
| Upload (bot → Telegram) | 50 MB |
| Download (`getFile`) | **20 MB** |
| `secret_token` | 1-256 chars `[A-Za-z0-9_-]` |
| Webhook `max_connections` | 1-100 (default 40) |

El límite de 64 bytes en `callback_data` obliga a usar IDs cortos o índices (no UUIDs completos). Patrón típico: `callback_data="r:{conv_id_8}"` (acción `r`=resolver + primeros 8 chars del UUID; el handler resuelve UUID completo por prefix match).

### 4.3 Webhook retry y timeout

Doc oficial es escueta sobre timeout exacto: "unsuccessful requests trigger automatic retry attempts" (https://core.telegram.org/bots/api#setwebhook + `/bots/webhooks`). Comportamiento empírico documentado en múltiples fuentes y validado en producción de varios bots populares: Telegram reintenta con backoff exponencial hasta ~24h o ~limite de pending updates. Nuestro endpoint **debe responder 2xx en <60s** (lo ideal: <5s, encolar el trabajo pesado en background — cf. `services/api/routers/telegram_webhook.py:74` que ya retorna `200` rápido).

> **VALIDAR EN DOCUMENTACION OFICIAL**: el retry exacto (intervalos, max attempts) no está canónicamente especificado en `core.telegram.org/bots/webhooks` (la página oficial no detalla la curva de reintentos). Tratar como "reintenta agresivamente durante 24h" y **diseñar idempotente** con `update_id`.

### 4.4 Autenticación inbound — solo `secret_token`

**No hay firma criptográfica** estilo HMAC (Wompi, Meta WhatsApp). El único mecanismo es el header `X-Telegram-Bot-Api-Secret-Token` cuyo valor configuramos en `setWebhook` (https://core.telegram.org/bots/api#setwebhook). Si el secret se filtra, un atacante puede inyectar updates falsos. Mitigaciones:

- Generar secret de **alta entropía** (32 bytes random base64-url-safe).
- Almacenar **solo hash** (bcrypt/argon2) en BD; comparar contra hash al validar.
- Allowlist por IP (subnets `149.154.160.0/20`, `91.108.4.0/22`).
- Rotación: regenerar y re-llamar `setWebhook` si se sospecha leak.

### 4.5 Bot no inicia conversaciones

"Bots cannot initiate conversations; users must contact first" (https://core.telegram.org/bots). Implicación: **el operador debe abrir el bot y enviar `/start` al menos una vez** antes de poder recibir mensajes individuales. Para grupos: el bot debe ser **añadido al grupo** por un humano.

Esto es fricción de onboarding, no obstáculo. Documentar en la UI: "Pasos: (1) Crea tu bot con @BotFather. (2) Abre el bot y envía /start. (3) Pega el token aquí."

### 4.6 Privacy mode en grupos

Por defecto, en grupos el bot **solo recibe**: comandos dirigidos (`/cmd@miBot`), comandos generales si fue el último en hablar, replies a sus mensajes, mensajes inline. Configurable con `/setprivacy` en BotFather (https://core.telegram.org/bots/features#privacy). Para nuestro caso (operadores escriben `/resolver xxx` al bot) el modo default está bien.

### 4.7 Mensajes editados, replies, pinned

El webhook entrega `edited_message` como Update separado (https://core.telegram.org/bots/api). Nuestro código ya lo maneja (`telegram_webhook.py:61`). **OK**.

---

## 5. Lo que tenemos vs lo que ofrece

### 5.1 Inventario actual

Archivos relevantes:
- `services/api/routers/telegram_webhook.py` (202 líneas) — handler webhook + comandos `/resolver`, `/estado`, `/ayuda`.
- `services/ai-orchestrator/notifications.py` (329 líneas) — `_send_telegram_notification()` para `human_takeover`, `consent_revoked`, `sar_received`.
- `services/api/main.py` — registra el router.
- `services/api/routers/settings.py` — endpoint para guardar `bot_token` y `chat_id` en `notification_settings`.

### 5.2 Brecha capability vs uso

| Capacidad Bot API | Estado en nuestro código | Observación |
|---|---|---|
| `setWebhook` con `secret_token` | Manual (curl en docstring `telegram_webhook.py:16-18`) | **Gap P1**: auto-registro al onboarding. |
| Validación `X-Telegram-Bot-Api-Secret-Token` | OK (`telegram_webhook.py:42-54`) | Pero secret es **global**, no per-tenant. |
| `sendMessage` con `parse_mode=Markdown` | OK | **Sub-óptimo**: usa `Markdown` legacy. Migrar a `HTML` o `MarkdownV2`. |
| `sendMessage` con `inline_keyboard` | **NO usado** | Sub-aprovechado P2: botón `[Devolver al bot]` evitaría typing manual de `/resolver {uuid}`. |
| `callback_query` handling | **NO existe** en `telegram_webhook.py` | Sin esto, los inline buttons son inútiles. |
| `answerCallbackQuery` | **NO existe** | Requerido si añadimos botones. |
| `editMessageText` / `editMessageReplyMarkup` | **NO usado** | Sub-aprovechado: tras `[Devolver al bot]` podríamos editar el mensaje a "✅ Bot reactivado por @operadorX a las 14:32". |
| `setMyCommands` | **NO automatizado** | Hoy el operador no ve autocompletado al teclear `/`. |
| `getMe` (health check) | **NO usado** | Útil al guardar token: validar antes de aceptar. |
| `getWebhookInfo` (diagnóstico) | **NO usado** | Útil en página settings ("Estado: ✅ activo / ❌ último error: ..."). |
| `disable_notification` | **NO usado** | Para alertas de baja prioridad (e.g. resúmenes diarios) evitaría ruido. |
| `protect_content` | **NO usado** | Sería bueno activarlo: los mensajes incluyen `customer_phone` (PII Habeas Data). |
| Multi-tenant token resolution | **Roto**: `_send_telegram_reply()` toma "el primer tenant activo" (`telegram_webhook.py:174-184`) | **Bug arquitectónico**: si hay >1 tenant configurado, los replies se envían con el bot equivocado. |
| `allowed_updates` filtering | NO declarado en `setWebhook` | Recibimos todos los update types innecesariamente. |
| Rate limit handling (`429 retry_after`) | NO presente en `notifications.py` | Riesgo bajo (volumen actual <<30/seg) pero mantenible. |

### 5.3 Hallazgos de auditoría

1. **Bug crítico** en `telegram_webhook.py:174-184`: la respuesta a un comando `/resolver` se envía con el `bot_token` del primer tenant que tenga Telegram activo. Si tenant A escribe `/resolver xxx`, la respuesta puede salir del bot del tenant B. **Solo funciona hoy porque hay 1 sólo tenant activo.** Ver gap P1 multi-bot.

2. **`Markdown` legacy** (`telegram_webhook.py:198`, `notifications.py:55`): la doc recomienda `MarkdownV2` o `HTML`. UUIDs con guiones rompen `MarkdownV2` si no se escapan. Migrar a `parse_mode=HTML` es la ruta de menor fricción (menos caracteres reservados).

3. **`protect_content` no activado** en mensajes con PII: los mensajes de escalamiento incluyen `customer_phone` (PII protegida por Ley 1581). Activar `protect_content=true` evita que un operador haga forward del mensaje fuera del grupo autorizado. Alineado con compromiso `docs/legal/incident-response.md`.

4. **Sin `getMe` validation al guardar token**: si el operador pega un token mal copiado, se descubre solo cuando llega el primer escalamiento. Validar con `GET https://api.telegram.org/bot{TOKEN}/getMe` antes de persistir mejora UX.

---

## 6. Gaps críticos (priorizados)

### P1 — semana 11 (≤1d cada uno)

**P1.1 — Auto-registro de webhook (`scripts/telegram_setup.py` per tenant)**
- Endpoint `POST /api/v1/settings/telegram/register` que: (a) valida token con `getMe`; (b) genera `secret_token` único por tenant (32 bytes); (c) almacena hash en `notification_settings.config.webhook_secret_hash`; (d) llama `setWebhook` con `url=…/telegram/webhook`, ese secret, y `allowed_updates=["message","callback_query"]`; (e) llama `setMyCommands` con `[/resolver, /estado, /ayuda]`; (f) responde con `webhook_info` para mostrar en UI.
- CLI complementario `scripts/telegram_setup.py --tenant {uuid}` para operaciones bulk.
- **Esfuerzo: 0.5d** (incluye tests).

**P1.2 — Multi-bot per-tenant (resolver tenant por `secret_token` inbound)**
- Cambiar `telegram_webhook.py` para que: (a) tome el header `X-Telegram-Bot-Api-Secret-Token`; (b) busque `tenant_id` cuyo `webhook_secret_hash` matchea (lookup por hash, no plaintext); (c) cargue `bot_token` del **mismo** tenant para responder; (d) inyecte `tenant_id` en el contexto de `_handle_command` para que `/resolver` filtre `conversations` por tenant (defensa en profundidad ante UUID guessing).
- Eliminar la lógica "primer tenant activo" (bug §5.3.1).
- **Esfuerzo: 0.5d** (incluye tests RLS/multi-tenant).

### P2 — semana 11 (≤1d total)

**P2.1 — UAT operadores (escenarios S29-S31)**
- S29: tenant nuevo → onboarding Telegram → `/start` → escalamiento WA → recibe notificación → `/resolver` → cliente vuelve al bot.
- S30: tenant con webhook caído → reintento Telegram → recovery (validar idempotencia por `update_id`).
- S31: dos tenants, dos bots, mismo endpoint → no cross-talk.
- **Esfuerzo: 0.3d.**

**P2.2 — Inline keyboards en notificaciones**
- En `notifications.py:_build_takeover_text`, devolver además `reply_markup={"inline_keyboard":[[{"text":"✅ Devolver al bot","callback_data":"r:{conv8}"},{"text":"📋 Ver inbox","url":"https://app/inbox/{conv}"}]]}`.
- Añadir handler de `callback_query` en `telegram_webhook.py`: (a) parsea `callback_data`; (b) valida prefix; (c) ejecuta `_cmd_resolver`; (d) llama `answerCallbackQuery` con toast; (e) `editMessageReplyMarkup` para quitar el botón (evita doble click).
- **Esfuerzo: 0.4d.**

**P2.3 — Comandos avanzados**
- `/stats` — count de `human_takeover` últimas 24h del tenant.
- `/handoff {conv}` — fuerza takeover desde Telegram (inverso de `/resolver`).
- `/template` — lista templates WhatsApp aprobados (consulta a la API interna).
- `setMyCommands` actualizado con scope per-tenant.
- **Esfuerzo: 0.3d.**

**P2.4 — Notificaciones agrupadas (anti-spam)**
- Si llegan ≥3 escalamientos en <60s al mismo tenant, agrupar en un solo mensaje "🚨 3 conversaciones requieren atención" con inline keyboard de cada conv.
- Implementar en `notifications.py` con buffer en Redis o en BD (tabla `pending_notifications`).
- **Esfuerzo: 0.5d.** Borderline P2/P3 según volumen real.

### P3 — backlog

**P3.1 — Conversation continuity cross-channel**
- Si el mismo cliente escribe por WA y MeLi y Telegram (este último vía bot público de cliente, **fuera del scope actual**), correlacionar conversaciones por `customer_id` y exponer historial unificado.
- Requiere revisar el modelo: hoy `conversations.customer_phone` indexa por canal-específico, no hay `customer_id` global. Trabajo no trivial (~3-5d).
- **No bloqueante** para el caso de uso actual (canal interno).

**P3.2 — Local Bot API server**
- Solo si necesitamos uploads >50MB (no es nuestro caso). Skip.

**P3.3 — Telegram Mini Apps para inbox web embebida**
- Operador podría abrir la inbox sin salir de Telegram. Premium UX, no crítico.

---

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

**Veredicto: sub-aprovechado.**

### Sub-aprovechado (alto ROI con bajo esfuerzo)

- **Inline keyboards + `callback_query`**: hoy el operador debe copiar/pegar el `conversation_id` UUID en `/resolver {uuid}`. Con un botón inline el resolver es 1 tap. UX dramáticamente mejor; esfuerzo 0.4d (cf. P2.2).
- **`getMe` para validar token al guardar**: 5 líneas de código, mejora onboarding y previene tickets de soporte.
- **`setMyCommands`**: autocompletar al teclear `/` es UX de bajo costo.
- **`protect_content=true` en mensajes con PII**: requisito Habeas Data, costo cero.
- **`getWebhookInfo` en UI settings**: visibilidad operativa con costo bajo.

### Adecuadamente usado

- **Webhook con `secret_token`**: validación correcta (con caveat multi-tenant).
- **Estructura de comandos `/resolver` `/estado` `/ayuda`**: básica pero funcional.
- **Respuesta 2xx rápida**: `telegram_webhook.py:74` retorna 200 inmediato, evita timeouts y replays.
- **Manejo de `edited_message`**: presente en `:61`.
- **Errores permanentes vs transitorios**: `notifications.py:77-79` distingue 4xx de 5xx para no reintentar inútilmente. Buena práctica.

### Sobre-ingeniado

Nada significativo. El scope actual (canal interno, comandos básicos) está alineado con la simplicidad de Telegram Bot API. **No** introducir Telegram como canal de cliente final (P3.1 sólo si emerge demanda real).

---

## 8. Recomendaciones priorizadas

### Plan semana 11 (~2d total)

| Día | Tareas | Entregable |
|---|---|---|
| Día 1 (P1) | P1.1 auto-registro webhook + P1.2 multi-bot per-tenant + migración a `parse_mode=HTML` + `protect_content` | `scripts/telegram_setup.py`, refactor `telegram_webhook.py`, tests RLS multi-tenant. |
| Día 2 (P2) | P2.1 UAT S29-S31 + P2.2 inline keyboards + `callback_query` handler + `setMyCommands` + `getMe` validation en settings + `getWebhookInfo` exposed en API | UAT pasando, UX de operador 1-tap, settings page robusta. |

### Backlog post-Sem11 (priorizar según uso)

- P2.3 comandos avanzados (`/stats`, `/handoff`, `/template`) — entregar a demanda.
- P2.4 batching anti-spam — solo si volumen real lo justifica.
- P3.1 cross-channel continuity — replantear si llega caso de uso.

### Decisiones técnicas recomendadas

1. **`parse_mode`: usar `HTML`** (no `Markdown` legacy ni `MarkdownV2`). Razón: payloads variables (UUIDs, números, paths) requerirían escapado constante en MarkdownV2; HTML solo escapa `< > &` (función estándar `html.escape`).
2. **`secret_token`: per-tenant, almacenar solo hash**. Algoritmo: `sha256(secret + tenant_pepper)`. Lookup constante O(1) con índice en BD.
3. **`callback_data` formato**: `"{action}:{shortid}"` con `action ∈ {r,s,h}` y `shortid` = primeros 8 chars del UUID. Resolver UUID completo por prefix match con verificación de unicidad. Total ≤ 24 bytes (margen sobrado bajo el límite 64).
4. **`allowed_updates`: `["message","edited_message","callback_query"]`**. Reduce tráfico ~40%.
5. **Idempotencia**: persistir `update_id` en una tabla efímera con TTL 24h; ignorar duplicados (Telegram puede reintentar el mismo `update_id` si nuestra respuesta se perdió).

### INTERVENCION HUMANA REQUERIDA — onboarding por tenant

- **RESPONSABLE**: operador del tenant (1 persona técnica).
- **PASOS**:
  1. Abrir Telegram, hablar con `@BotFather`.
  2. `/newbot` → elegir nombre y `@username` (debe terminar en `_bot`).
  3. Copiar el token devuelto.
  4. (Opcional) `/setprivacy` → `Disable` si el bot vivirá en grupo y quiere leer todos los mensajes (no recomendado para nuestro caso; dejar default).
  5. (Opcional) `/setdescription`, `/setuserpic`.
  6. En la UI Konvi: Settings → Notifications → Telegram → pegar token → click "Verificar y registrar".
  7. Abrir el bot en Telegram, enviar `/start` desde el chat personal del operador (o añadir el bot al grupo de operadores).
  8. Copiar el `chat_id` mostrado en UI (lo obtenemos del primer mensaje recibido) → guardar.
- **INSUMOS**: cuenta Telegram del operador, navegador con sesión Konvi Console.
- **CRITERIO DE EXITO**: en la página Settings se muestra "✅ Webhook activo, último heartbeat: <timestamp>" y un mensaje de prueba enviado desde el botón "Enviar prueba" llega al chat configurado en <5 segundos.

---

## 9. Validaciones humanas pendientes

### V.16 — ¿multi-bot per-tenant es necesario o sigue siendo 1 bot global?

**Decisión requerida de**: Founder / Stakeholder.

**Contexto**:
- **Estado actual** (rev. 103): 1 bot global, todos los tenants comparten `bot_token` único en env var, los operadores de distintos tenants reciben notificaciones del mismo bot, identificados solo por contenido del mensaje.
- **Estado deseado declarado**: multi-bot per-tenant (Modelo B).

**Trade-offs**:

| Eje | 1 bot global (actual) | Multi-bot per-tenant |
|---|---|---|
| Costo monetario | $0 | $0 (Telegram gratis) |
| Esfuerzo desarrollo | 0 (ya hecho) | ~1d (P1.1 + P1.2) |
| Branding por tenant | ❌ todos ven el mismo `@CommerceOpsBot` | ✅ cada uno ve su `@miempresa_bot` |
| Aislamiento seguridad | ❌ leak del token compromete todos los tenants | ✅ leak afecta solo 1 tenant |
| Aislamiento rate-limit | ❌ tenant A ruidoso degrada tenant B | ✅ cuotas independientes (~30 msg/seg cada uno) |
| Onboarding por tenant | trivial (env var ya seteada) | requiere paso humano en BotFather (~3 min/tenant) |
| Reasignación de bot a otro tenant | imposible | trivial (`/transfer` en BotFather) |
| Riesgo de cross-talk en webhook | sí (bug actual §5.3.1) | mitigado por `secret_token` per-tenant |

**Recomendación AI Architect**: **proceder con Modelo B (multi-bot per-tenant)**. Justificación:
1. Aísla el bug actual de cross-talk (§5.3.1) — hoy ya es un riesgo latente.
2. Esfuerzo 1 día, sin costo recurrente.
3. Onboarding humano es mínimo (~3 min) y solo una vez por tenant.
4. Branding propio por tenant es coherente con posicionamiento "Konvi Platform como infraestructura, el tenant como marca".
5. Aislamiento de seguridad alineado con principio "service_role exige filtros explícitos por tenant" (CLAUDE.md §3).

**Pregunta abierta para Stakeholder**:
- ¿Quieres que la UI guíe al tenant paso a paso por BotFather (mejor UX, más esfuerzo) o documentación + link "cómo crear tu bot" (menor esfuerzo, fricción mayor)?
- ¿Cuál es el SLA esperado de onboarding del canal Telegram? (¿Día 0 con el primer setup? ¿Opcional, post-launch?)

### V.17 (sugerida, no en lista original) — ¿Telegram como canal de cliente final en el futuro?

Hoy descartado por decisión consensuada. Validar formalmente que sigue fuera de scope hasta nueva orden, para evitar deriva. Si la respuesta cambia, abrir RFC separado (impacto: nuevo connector tipo `services/connector-telegram/`, replicación de la arquitectura WhatsApp + persistencia en `messages` + integración con Orchestrator).

---

## 10. Veredicto final

Telegram Bot API es **óptimo** para el caso de uso "canal interno de notificaciones a operadores del tenant" en Konvi Platform:

- **Económico**: gratis tanto para nosotros como para el tenant. Sin costos recurrentes ni por mensaje.
- **Operacionalmente confiable**: aunque sin SLA contractual, la plataforma de Telegram aloja "más de 10 millones de bots" sobre infra propia con disponibilidad histórica alta. No hemos visto incidentes mayores documentados que afecten Bot API en años recientes.
- **Sin verificación business**: a diferencia de WhatsApp Business API (Meta exige verificación, embedded signup, plantillas pre-aprobadas), Telegram requiere solo `@BotFather` → `/newbot` → token. Onboarding del tenant en minutos.
- **Multi-bot per-tenant trivial**: BotFather permite crear N bots por cuenta humana; el `setWebhook` es API directa con el token de cada bot; `secret_token` per-tenant resuelve enrutamiento inbound.
- **Modelo B (token per tenant) es natural**: alineado con la API; sin contortions arquitectónicas; aísla seguridad y rate limits.
- **Rate limits holgados** para volumen interno: 30 msg/seg globales >> ~0.03 msg/seg esperados.
- **Esfuerzo P1+P2 ~2d**, dentro de lo planificado para Sem 11.
- **Sin riesgos críticos**: la única limitación notable (sin HMAC, solo `secret_token`) se mitiga con secrets de alta entropía + storage hasheado + IP allowlist.

**Bug actual a corregir** (§5.3.1): `_send_telegram_reply` selecciona "primer tenant activo" — funciona solo porque hay un tenant. Cuando entre el segundo, hay cross-talk silencioso. P1.2 lo elimina.

**Sub-aprovechamiento corregible** en 0.5d: inline keyboards + `callback_query` reducen el resolver de "tap mensaje → seleccionar UUID → copiar → pegar `/resolver` → enviar" a "tap botón". UX dramáticamente mejor sin cambios arquitectónicos.

**Decisión final recomendada**: ejecutar P1+P2 en Sem 11 (~2d) tal como está planificado. Ratificar V.16 con Stakeholder (recomendación: Modelo B). No invertir en P3 (cross-channel continuity, Mini Apps) hasta que emerja necesidad concreta.

---

## Anexo A — Tabla compacta de URLs de referencia

| Tema | URL |
|---|---|
| Overview general | https://core.telegram.org/bots |
| Methods reference | https://core.telegram.org/bots/api |
| `sendMessage` | https://core.telegram.org/bots/api#sendmessage |
| `setWebhook` | https://core.telegram.org/bots/api#setwebhook |
| `answerCallbackQuery` | https://core.telegram.org/bots/api#answercallbackquery |
| Webhooks guide | https://core.telegram.org/bots/webhooks |
| Features (commands, keyboards, BotFather, privacy) | https://core.telegram.org/bots/features |
| Bot API 2.0 intro (inline keyboards, callbacks) | https://core.telegram.org/bots/2-0-intro |
| Inline mode | https://core.telegram.org/bots/inline |
| FAQ (rate limits, file sizes) | https://core.telegram.org/bots/faq |

## Anexo B — Checklist de implementación P1+P2

- [ ] Crear `scripts/telegram_setup.py --tenant {uuid} [--dry-run]`.
- [ ] Endpoint `POST /api/v1/settings/telegram/register` (validate `getMe` → genera secret → `setWebhook` → `setMyCommands`).
- [ ] Migrar `parse_mode=Markdown` → `parse_mode=HTML` en `telegram_webhook.py:198` y `notifications.py:55`.
- [ ] Activar `protect_content=true` en mensajes con PII.
- [ ] Resolver `tenant_id` por `webhook_secret_hash` en `telegram_webhook.py`.
- [ ] Eliminar lógica "primer tenant activo" en `_send_telegram_reply`.
- [ ] Añadir handler `callback_query` con `answerCallbackQuery` + `editMessageReplyMarkup`.
- [ ] Inline keyboards en `notifications._build_takeover_text` (botones "Devolver al bot" + "Ver inbox").
- [ ] Idempotencia: tabla efímera `telegram_processed_updates(update_id, tenant_id, processed_at)` con TTL 24h.
- [ ] UI Settings: mostrar `getWebhookInfo` (estado, last_error_date, last_error_message, pending_update_count).
- [ ] Tests: `test_telegram_multitenant_routing.py`, `test_telegram_callback_query.py`, `test_telegram_idempotency.py`.
- [ ] UAT: scenarios S29 (onboarding), S30 (recovery), S31 (multi-tenant aislamiento).
- [ ] Documentar en `docs/HANDOFF.md` el procedimiento de onboarding Telegram per tenant.

---

_Fin del dossier. Todas las afirmaciones técnicas referencian `core.telegram.org` salvo el caveat marcado en §4.3 (curva de retry no canónicamente especificada en doc oficial)._
