# WhatsApp — Meta Cloud API, Model B per-tenant (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** — matriz abajo §"Alineación doc oficial".

> **⚠️ OPS URGENTE (deadline 2026-09-30):** desde **2026-10-01 los service messages (free-form en ventana de servicio) dejan de ser gratis**, y una WABA **sin método de pago registrado al 2026-09-30 deja de recibir TODOS los service messages** (todo el tráfico del bot y operadores). En Model B cada tenant tiene su propia WABA → cada tenant debe registrar su método de pago en su WABA antes de esa fecha. Es acción de ops/founder, no de código. [Doc oficial pricing/non-template-messages](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages).

## Estado

**LIVE — Model B (ADR-0023: direct provider per tenant)**. Cada tenant conecta SU propio WABA con SU propio System User token; la plataforma no intermedia la relación contractual con Meta. Significa:

- Inbound y outbound reales en producción, con routing per-tenant, HMAC per-tenant e inbox durable.
- **Cero env vars Meta globales**: `META_APP_SECRET` / `META_VERIFY_TOKEN` fueron eliminadas del connector (0 lectores verificado, `render.yaml:142-144`) — app_secret y verify_token se resuelven per-tenant desde Vault/credentials.
- Graph API **v22.0** en todo el runtime (`whatsapp_sender.py:19-20`, `meta_media.py:7` api y orchestrator, `health_metrics.py:184`). Cero referencias a v21.0 en código.
- Nota documental: el modelo "Embedded Signup / Tech Provider" descrito en `meta-suite.md` (histórico) NO es el modelo implementado; el implementado es Model B.

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Connector (webhook gateway) | `services/connector-whatsapp/` | — |
| — routing + handshake + inbox pre-ACK | `services/connector-whatsapp/routers/webhook.py` | 197 |
| — HMAC per-tenant, cap, rate-limit, cross-tenant | `services/connector-whatsapp/dependencies/meta.py` | 582 |
| — inbox durable + re-drive | `services/connector-whatsapp/services/inbox.py` | 222 |
| — parser de payloads + eventos template | `services/connector-whatsapp/services/parser.py`, `services/template_events.py` | 398 / 496 |
| — persistencia de mensajes | `services/connector-whatsapp/services/db_persistence.py` | 344 |
| Sender outbound (bot + humano) | `services/ai-orchestrator/whatsapp_sender.py` | 582 |
| Worker de colas (outbound, re-drive Wompi, CSW) | `services/ai-orchestrator/worker.py` | — |
| Descarga de media (audio) | `services/api/integrations/meta_media.py` + espejo en orchestrator | — |
| Config de credenciales por tenant | `services/api/routers/integrations.py` (`POST /whatsapp/credentials:91`) | — |
| Motor de plantillas HSM | `services/api/lib/whatsapp_templates.py` + ADR-0016 | — |
| Opt-out STOP / Habeas Data | `services/ai-orchestrator/lib/whatsapp_optout.py`, `lib/habeas_data_request.py` | — |
| ADR rector | `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md` | — |

## Flujos implementados

### 1. Onboarding del tenant (Model B)

1. El owner genera en Meta Business Manager un **System User token** permanente con exactamente 2 permisos sobre su WABA: `whatsapp_business_messaging` (enviar) + `whatsapp_business_management` (test de conexión / leer phone_number).
2. Lo carga en Ajustes → Integraciones → WhatsApp → `POST /api/v1/integrations/whatsapp/credentials` [owner/manager] (`integrations.py:91-137`): el token se cifra en Vault y `tenant_integrations.credentials` queda con el shape exacto que el connector lee (`access_token_secret_id`, `phone_number_id`, `verify_token`, `app_secret`), más `access_token_rotated_at`.
3. Registra el webhook en su app Meta: `https://konvi-connector.onrender.com/api/v1/whatsapp/webhook/{tenant_id}` con SU `verify_token`.

### 2. Inbound (Meta → connector → DB)

Receptor: `GET|POST /api/v1/whatsapp/webhook/{tenant_id}` (`webhook.py:45,153`; mount `/api/v1/whatsapp` en `main.py:48`).

1. **Challenge GET**: `hub.verify_token` contra el verify_token **del tenant** (en claro en `credentials.verify_token`, NO en Vault — `webhook.py:50-63`).
2. **Perímetro** (antes de leer body): Content-Length cap **512 KB** → 413 (`meta.py:77,497-500`, con backstop para chunked) + rate-limit per-IP → 429 (`meta.py:66`).
3. **HMAC** `X-Hub-Signature-256` con el **app_secret del tenant** desde Vault (`meta.py`); métricas `hmac_ok/fail`.
4. **Defensa cross-tenant**: tras HMAC OK, se verifica que el `phone_number_id` del payload resuelva al MISMO `tenant_id` del path (invariant; `meta.py:16-17,397-453`). Un tenant con app_secret válido no puede inyectar eventos en el buzón de otro.
5. **Inbox durable pre-ACK**: payload (ya HMAC-verificado) a `whatsapp_webhook_inbox` ANTES del 200 (`webhook.py:168-186`; migración `20260725060000`; espejo del patrón Wompi).
6. Parser: arrays `entry/changes/messages` completos (no solo primer elemento), replies (`context.id`), interactivos (`button_reply`/`list_reply`), y field `message_template_status_update` → actualiza `whatsapp_templates.status` filtrando por tenant verificado (`parser.py:215,250`, `template_events.py:64-116`).
7. Mensaje persistido con `processing_status='pending'` → visible en Inbox; el orchestrator lo procesa (FSM del bot).

### 3. Outbound (bot y operador humano)

1. Humano: `POST /api/v1/conversations/{id}/send` (solo `human_takeover`) → persiste + encola en pgmq `whatsapp_outbound_messages`. Bot: el orchestrator encola directo.
2. El worker consume la cola (`WHATSAPP_OUTBOUND_QUEUE_*`) y `whatsapp_sender.py` POSTea a `https://graph.facebook.com/v22.0/{phone_number_id}/messages` (`:186` free-form, `:419,538` templates) con el access_token del tenant (Vault; exige `status='connected'`).
3. Resultado: `processing_status='processed'` + `meta_message_id`, o `failed` tras `WHATSAPP_OUTBOUND_MAX_ATTEMPTS=5`.

### 4. Ventana de servicio 24 h (CSW) y plantillas HSM

- `META_CSW_HOURS=24` (`render.yaml:424-425`, `.env.example:202`): todo outbound proactivo free-form se filtra por último inbound del cliente < 24 h.
- **131047 no se reintenta** (`whatsapp_sender.py:76`, `worker.py:1190-1199`): fuera de ventana Meta rechaza; reintentar quema llamadas y arriesga el WABA. Mitigación: las notificaciones post-despacho salen TAMBIÉN por email (obligatorio para crear pedido).
- **HSM**: sync de estados vía `message_template_status_update`; solo `APPROVED` es enviable (`whatsapp_templates.py:100-102`). Categorías y calidad (`template_quality_update`) también sincronizadas.

### 5. Opt-out y Habeas Data

- **STOP keyword** (`STOP`/`BAJA`/`CANCELAR` y variantes): soft opt-out — conversación a `opted_out` + `consent_revoked_at`; el orchestrator skipea inbound y bloquea outbound proactivo/HSM (`lib/whatsapp_optout.py`, `conversation_contract.py:13,25`, `orchestrator.py:572-573`, `worker.py:2919-2920`). Reactivación solo manual por operador (botón "Reactivar bot" en Inbox).
- **Solicitudes no-keyword** de derechos (Ley 1581): detección + acuse + escalación humana (`lib/habeas_data_request.py`); notificaciones email vía Resend.

### 6. Multimodal (audio)

`meta_media.py` descarga 2-step (`GET v22.0/{media_id}` → URL temporal → bytes) con Bearer del tenant, caché 240 s; el audio se transcribe inline con Gemini y el FSM sigue con texto. Flags: `MULTIMODAL_AUDIO_ENABLED=true`, `META_MEDIA_MAX_BYTES=16777216`, `META_MEDIA_DOWNLOAD_TIMEOUT_SECONDS=10`. Imagen: no procesada (gate humanizado).

## Config por tenant vs global

### Por tenant — `tenant_integrations` (`provider='whatsapp'`, `status='connected'`)

```json
"credentials": {
  "access_token_secret_id": "… (Vault)",
  "app_secret_secret_id": "… (Vault)",
  "phone_number_id": "111222333",
  "verify_token": "<en claro — lo usa Meta en el challenge GET>"
}
```

El System User token y el app_secret viven cifrados en Vault; `phone_number_id` y `verify_token` en claro en credentials JSONB (el verify_token lo debe poder leer el connector sin Vault para el handshake). Config vía UI Integraciones [owner/manager].

### Globales (env vars — ninguna credencial Meta)

| Var | Valor | Servicio | Qué controla |
|---|---|---|---|
| `WHATSAPP_OUTBOUND_QUEUE_ENABLED` | `true` | orchestrator | Kill-switch cola outbound |
| `WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH` / `_VT_SECONDS` | `20` / `90` | orchestrator | Tuning de la cola |
| `WHATSAPP_OUTBOUND_MAX_ATTEMPTS` | `5` | orchestrator | Intentos antes de `failed` |
| `META_CSW_HOURS` | `24` | orchestrator | Ventana de servicio Meta |
| `MULTIMODAL_AUDIO_ENABLED` | `true` | orchestrator | Kill-switch transcripción |
| `META_MEDIA_MAX_BYTES` / `META_MEDIA_DOWNLOAD_TIMEOUT_SECONDS` | `16777216` / `10` | orchestrator | Límites de media |
| `WA_INBOX_REDRIVE_ENABLED` | `true` (default código) | connector | Kill-switch del re-drive (`main.py:17`) |

Defaults de código del inbox (`inbox.py:24-33`): `WA_INBOX_LEASE_SECONDS=120`, `WA_INBOX_MAX_ATTEMPTS=5`, `WA_INBOX_REDRIVE_SECONDS=60`, `WA_INBOX_REDRIVE_BATCH=20`, `WA_INBOX_RETENTION_DAYS=7`.

## Seguridad

- **HMAC per-tenant** (app_secret Vault) + **invariant cross-tenant** phone_number_id→tenant (defensa en profundidad post-firma).
- **Cap 512 KB** + rate-limit per-IP en el único endpoint internet-facing sin JWT.
- **Inbox durable** con lease de visibilidad, máx 5 intentos y dead-letter observable.
- Aislamiento: filtros `tenant_id` explícitos + RLS; el lookup phone→tenant está cacheado 300 s y marcado `tenant_filter:exempt` auditado (`meta.py:438`).
- Anti-spam / políticas Meta: solo Cloud API oficial, ventana 24h, templates APPROVED, opt-out STOP con bloqueo de proactivos.

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| Meta cae en outbound | Reintento por cola (VT 90 s, máx 5) → `failed` visible en Inbox |
| Crash del connector entre ACK y procesamiento | Re-drive del inbox (cada 60 s, batch 20, máx 5 → dead-letter con `last_error`) |
| Token del tenant inválido/revocado | Envío falla visible (`failed` tras 5 intentos); diagnóstico manual: 401/403 desde Meta = permisos o asset assignment del System User sobre el WABA |
| Cliente fuera de ventana 24h | 131047 sin reintento; notificación migrada a email |
| HMAC inválido sostenido | Métrica `hmac_fail_*` en `GET /api/v1/whatsapp/health/metrics` del connector (agregada, sin PII, pública per Q10 ADR-0023) |
| Vault cae en el webhook | El evento no se puede verificar → rechazo; el inbox no captura lo no firmado (por diseño) |

## Operación

- **Manual por tenant**: crear System User + token (2 permisos, expiración Never), cargar credenciales en Integraciones, registrar webhook en su app Meta con su verify_token, suscribir fields `messages` + `message_template_status_update`.
- **Manual de plataforma**: ninguna credencial Meta global que rotar; la app Meta de plataforma solo existió para el modelo viejo (Model B la elimina del path runtime).
- **Plantillas HSM**: el tenant las crea en su WhatsApp Manager (o vía motor ADR-0016), Meta las aprueba; el estado se sincroniza solo por webhook. Founder-gate pendiente: plantillas por tenant para flujos proactivos (cart abandonment ya tiene `cart_abandoned_24h_v1` MARKETING).
- **Monitoreo disponible**: `GET /api/v1/whatsapp/health/metrics` del connector (HMAC ok/fail, vault/cache hits, `inbox_depth`, `inbox_dead_lettered` — los dos últimos son los alertables, `webhook.py:34-42`); métricas del worker `wa_outbound_sent/ack_pending`.

## Alineación doc oficial (Track 6 — fetch live 2026-08-22)

Matriz capacidad × doc × código ejecutada el 2026-08-22 (developers.facebook.com vía mirror de lectura — el fetch directo está bloqueado desde esta red; URLs canónicas citadas). **Veredicto: nada de lo que usamos está deprecado.** Graph API v22.0 vive hasta **2027-05-20**; el bump calendarizado Q4-2026 sigue correcto y ya tiene checklist (abajo).

**Adoptado en esta revalidación (código, 2026-08-22):**

| Cambio | Detalle |
|---|---|
| Estados de template HSM ampliados | CHECK constraint DB + enums (`template_events.py`, `whatsapp_templates.py`): +ARCHIVED/UNARCHIVED/DELETED/IN_APPEAL/LOCKED/REINSTATED/PENDING_DELETION. Enviabilidad = `SENDABLE_STATUSES` {APPROVED, REINSTATED, UNARCHIVED} (sender actualizado) |
| Health check sin campo deprecado | `health_metrics.py` pide `whatsapp_business_manager_messaging_limit` (fallback al legado si Graph lo rechaza); umbrales al modelo per-portfolio (250→2K→10K→100K→∞) |
| `template_category_update` | Parser + persistencia: recategorización de Meta → UPDATE `whatsapp_templates.category` (cambia el PRECIO del template) |
| `user_preferences` | Parser + persistencia: **stop nativo de marketing** → `contacts.consent_comercial_revoked_at` (misma barrera que la keyword STOP; `outbound_gate` ya la consulta). El **resume nativo NO muta** — el consent comercial Ley 2300 se gana por nuestro flujo, no por Meta |
| `account_alerts` | Persistidos en `tenant_provider_health` (antes: solo log — un WABA flagged era invisible) |
| Mark-as-read + typing indicator | `whatsapp_sender.mark_message_read()` cableada al claim del inbound en `worker.py`: ✓✓ azul + "escribiendo…" mientras corre la cascada LLM (mitigación UX de la latencia A5) |

**Diseñado para el futuro (puntos de extensión documentados):** bump v22→v24/v25 (checklist: statuses sin objeto `conversation`, límites por `business_capability_update`, system messages BSUID); mensajes interactivos outbound (reply buttons / CTA URL / listas — el parser inbound ya los lee; el uso en flujos del bot es de B-1); WhatsApp Flows para checkout; media upload + `type:document` (facturas/guías PDF); BSUID como identidad secundaria cuando Meta lo haga obligatorio; MM Lite API si el volumen de marketing lo justifica.

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| M19 | Medio | verify_token de dev en claro + tenant UUID hardcodeado en migración backfill `20260622_whatsapp_model_b_backfill_konvi_dev.sql` |
| M10 | Medio | Post-venta fuera de ventana 24h: el bot promete "recibirás confirmación por este chat" pero 131047 mata el canal; email mitiga, no elimina |
| A5 | Alto | Cascada LLM peor caso ~5 min vs heartbeat Render 120 s → posible restart a mitad de turno con outbound duplicado |
| B4 | Bloqueante | UAT E2E conversacional stale desde 2026-05 (5 fixes de bot en ago sin re-certificación) |
| M13 | Medio | ADR 0023 duplicado (meta-model-b vs shipping-provider-pattern) — citar siempre con título |
| — | Bajo | `verify_token` en claro en credentials (por diseño del handshake GET); app_secret sí va a Vault |

## Referencias oficiales

- Cloud API mensajes y webhooks: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages · /webhooks/payload-examples
- Error 131047 (re-engagement / ventana 24h): docs Meta Cloud API — comportamiento verificado en `worker.py:1190-1199`.
- Graph API v22.0: verificado por grep en todo el runtime (`graph.facebook.com/v22.0`, 3 archivos, 0 referencias a otra versión).
