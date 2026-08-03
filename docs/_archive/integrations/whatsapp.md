> **⚠️ ARCHIVADO — 2026-08-02.** Supersedido por `docs/integrations/whatsapp-meta.md` (conector WhatsApp Model B per-tenant, vigente). Conservado solo como registro histórico. No usar como referencia operativa.

---

# Integración WhatsApp Cloud API (estado real)

Última actualización: 2026-04-21

---

## Arquitectura final

La integración WhatsApp está separada en dos piezas:

1. `services/connector-whatsapp`
- Recibe webhooks de Meta
- Valida firma HMAC (`X-Hub-Signature-256`)
- Resuelve `tenant_id` por `meta_waba_id`
- Persiste inbound en `messages`
- No envía mensajes

2. `services/api` + `services/ai-orchestrator`
- API encola outbound humano; Orchestrator ejecuta envío real a Meta Graph API
- Usan credenciales por tenant desde `tenant_integrations`

Fuente única de credenciales de envío:
- `tenant_integrations` (`provider='whatsapp'`, `status='connected'`)

No existe fallback runtime a `META_ACCESS_TOKEN` / `WHATSAPP_PHONE_ID`.

---

## Flujo inbound (Meta -> Connector -> DB)

1. Meta POSTea a `/api/v1/whatsapp/webhook`
2. Se valida firma con `META_APP_SECRET`
3. Se parsea payload (arrays `entry/changes/messages`, no solo primer elemento), incluyendo señales de contexto:
- `context.id` (reply a mensaje previo)
- `context.from`
- detalles de interacción (`interactive.button_reply`, `interactive.list_reply`, `button`)
4. Se resuelve tenant por `tenants.meta_waba_id`
5. Se inserta mensaje inbound con:
- `processing_status='pending'`
- `processed=false` (compatibilidad)
- `payload` JSONB (contexto webhook normalizado)

El mensaje queda visible en Inbox aunque sea no-text.

---

## Flujo outbound (Inbox/API -> Queue -> Worker -> Meta)

1. API recibe `POST /api/v1/conversations/{id}/send` (solo `human_takeover`)
2. API persiste outbound en `messages` como `processing_status='pending'`
3. API encola payload en `pgmq` (`whatsapp_outbound_messages`)
4. AI Orchestrator consume cola y ejecuta envío real a Meta
5. Worker actualiza `messages`:
- éxito -> `processing_status='processed'`, `meta_message_id`
- fallo definitivo -> `processing_status='failed'` (tras max intentos)

El sender efectivo de outbound humano es:
- `services/ai-orchestrator/whatsapp_sender.py`

Reglas de credenciales:
- lee `phone_number_id` y `access_token` desde `tenant_integrations`
- exige `status='connected'`
- si faltan credenciales válidas, no envía

Endpoint Meta:
- `POST /v21.0/{phone_number_id}/messages`

---

## Contrato conversacional relevante para WhatsApp

Estados canónicos de conversación:
- `bot_active`
- `human_takeover`
- `closed`

Comportamiento:
- `human_takeover`: bot silenciado
- `closed`: bot silenciado (sin reapertura automática)
- no-text inbound: se escala a `human_takeover`, `processing_status='skipped'`, `skip_reason='non_text_requires_human'`

---

## Variables de entorno requeridas

### Connector
- `META_APP_SECRET`
- `META_VERIFY_TOKEN`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### API/Orchestrator
No requieren `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` en env.
Usan credenciales por tenant en DB.

### Orchestrator queue runtime
- `WHATSAPP_OUTBOUND_QUEUE_ENABLED`
- `WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH`
- `WHATSAPP_OUTBOUND_QUEUE_VT_SECONDS`
- `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`

---

## Seguridad y cumplimiento

- Solo WhatsApp Cloud API oficial (Meta v21.0)
- Sin librerías no oficiales
- Política anti-spam: no envíos masivos ni fuera de reglas de ventana/template
- Aislamiento tenant: filtros explícitos por `tenant_id` + RLS donde aplica
- `service_role` puede bypassar RLS: no confiar solo en RLS para rutas privilegiadas

### Permisos del System User Token (rev. 67)

Para conectar WhatsApp por tenant, el operador genera un System User token en
Meta Business Manager con **2 permisos** sobre el WABA del tenant:

| Permiso | Para qué |
|---|---|
| `whatsapp_business_messaging` | Enviar mensajes (`POST /v21.0/{phone_id}/messages`) |
| `whatsapp_business_management` | Test de conexión y lectura del phone_number (`GET /v21.0/{phone_id}`) |

NO marcar otros permisos. Token expiration: **Never** (System User permanente).
El token se guarda cifrado en Supabase Vault (`tenant_integrations.credentials`).

### Ventana 24h Meta (rev. 67)

Regla oficial: el bot/operador solo puede enviar mensajes free-form (texto plano)
DENTRO de las 24h tras el último mensaje del cliente. Fuera de ventana, Meta
rechaza el envío y aplicar repetidamente puede llevar a baneo del WABA.

Implementación en este proyecto:

- **Backend** (`services/api/routers/conversations.py`): `_check_24h_window_or_raise`
  consulta `MAX(created_at) FROM messages WHERE direction='inbound'` antes de
  permitir el envío. Si fuera de ventana → 422 con `{code, message, hours_since_last_inbound}`.
- **Frontend Inbox**: banner amarillo si quedan <4h, rojo si expirada o sin
  inbound previo. Solo visible en `human_takeover`.
- **Bot conversacional**: respeta la ventana implícitamente (solo responde cuando
  el cliente escribe, lo cual reabre la ventana).

**Templates aprobados (futuro)**: cuando se requiera enviar fuera de ventana
(ej. cart abandonment, notificaciones proactivas), registrar plantilla en
Meta Business Manager → extender `POST /conversations/{id}/send` para aceptar
`template_name` + variables.

### Multimodal — comprensión de audio (rev. 67)

El bot entiende mensajes de voz del cliente vía Gemini 2.5 Flash multimodal nativo.

Flujo:
1. Connector parsea el webhook Meta y extrae `media_id` + `media_mime` del audio.
2. Persiste en `messages.media_id` + `messages.media_mime` (migración 20260428000002).
3. Orchestrator: `services/meta_media.py.fetch_media_bytes()` descarga 2-step
   (resolver URL temporal + bytes) con Bearer del tenant. Caché TTL 240s.
4. `_transcribe_audio_or_none()` envía el audio inline al modelo
   (`Part(inline_data=Blob)`). Si éxito, sustituye `content` por la transcripción
   y `content_type='text'`. El flow normal del FSM continúa con ese texto.
5. Si descarga/transcripción falla, fallback al gate humanizado actual
   ("solo manejo texto, te paso con asesor si insistes").

Mimes soportados: `audio/ogg`, `audio/mp3`, `audio/mpeg`, `audio/wav`, `audio/aiff`,
`audio/aac`, `audio/flac`. Tamaño máx: `META_MEDIA_MAX_BYTES` (default 16 MB).

Feature flag: `MULTIMODAL_AUDIO_ENABLED` (default `true`). Apagable en caliente
sin redeploy si Gemini falla masivamente o Meta cambia el contrato de descarga.

**Imagen y otros media**: NO procesados aún (futuro F8). El bot avisa con el
gate humanizado.

### Troubleshooting

- **Error "Fuera de ventana 24h"** (HTTP 422 `WINDOW_EXPIRED`): pedir al cliente
  que escriba primero, o registrar plantilla aprobada para usar `template_name`.
- **Error de permisos al test de conexión** (HTTP 401/403 desde Meta): verificar
  que el System User tiene asset assignment al WABA + permisos
  `whatsapp_business_messaging` + `whatsapp_business_management`.
- **Audio del cliente no se procesa**: verificar `MULTIMODAL_AUDIO_ENABLED=true`
  + el mime está en lista soportada + el audio < 16 MB.

---

## Referencias

- `services/connector-whatsapp/routers/webhook.py`
- `services/connector-whatsapp/services/parser.py`
- `services/connector-whatsapp/services/db_persistence.py`
- `services/api/routers/conversations.py`
- `services/ai-orchestrator/whatsapp_sender.py`
- `services/ai-orchestrator/worker.py`
- `services/ai-orchestrator/orchestrator.py`
- Docs oficiales Meta (validación):
  - https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
  - https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
