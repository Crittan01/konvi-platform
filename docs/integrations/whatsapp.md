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
