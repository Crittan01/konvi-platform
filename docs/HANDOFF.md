# Handoff — Estado Operativo Real (2026-04-20, rev. 27)

Este documento describe el estado operativo real de `develop`.
Para árbol funcional y semántica de dominio: `.context/00-product.md`.
Para estado por módulo: `.context/01-state.md`.
Los documentos de `docs/deployment/` y parte de `docs/operations/` contienen
histórico de fases previas; ante conflicto, este HANDOFF y `.context/01-state.md`
tienen prioridad.

---

## Resumen ejecutivo

- Tenant Console: ✅ live (fases 1–11.5 completas)
- Platform Console: ❌ fuera de alcance (bloqueante OQ-P01)
- Servicios live en Render: `web`, `connector-whatsapp`, `api`, `ai-orchestrator`
- DB canónica: `supabase/migrations/` (42 migraciones)

---

## Contratos runtime vigentes

### Conversaciones
Contrato único end-to-end:
- `bot_active`
- `human_takeover`
- `closed`

No hay valores legacy válidos en runtime.

### Procesamiento inbound
`messages` usa resultado explícito:
- `processing_status`: `pending | processed | skipped | failed`
- `skip_reason`
- `last_error`
- `processing_attempts`

El worker procesa solo `processing_status='pending'`.
`processed` queda como compatibilidad de lectura, no como driver del loop.

### Human takeover / closed
- `human_takeover`: el bot queda silenciado.
- `closed`: el bot queda silenciado y no reabre automáticamente.
- No-text inbound: no auto-respuesta; se escala a `human_takeover` y el mensaje queda visible en Inbox.
- Escalamiento a `human_takeover` publica evento a cola durable Supabase Queues (`pgmq`)
  vía trigger DB sobre `conversations.status`.
- El AI Orchestrator consume esa cola y notifica por canales activos del tenant
  (`telegram` activo, `email` preparado placeholder).

### Outbound humano Inbox -> WhatsApp
- Endpoint `POST /api/v1/conversations/{id}/send` encola outbound en Supabase Queues
  (`whatsapp_outbound_messages`) y persiste `messages.processing_status='pending'`.
- El AI Orchestrator consume la cola, envía a Meta con credenciales del tenant y actualiza `messages`:
  - éxito: `processed`
  - error transitorio: retry por visibilidad (`vt`)
  - error definitivo: `failed` al superar `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`

### RBAC runtime
Roles vivos:
- `owner`
- `manager`
- `operator`

`agent` queda solo en migraciones históricas/documentación de migración.

### WhatsApp credentials
Fuente única runtime para envío:
- `tenant_integrations` por `tenant_id` (`provider='whatsapp'`, `status='connected'`)

No hay fallback a `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` en senders.

### MeLi OAuth
`state` endurecido:
- HMAC firmado
- expiración (`MELI_OAUTH_STATE_TTL_SECONDS`)
- nonce one-time persistido (`integration_oauth_states`)
- callback rechaza `state` faltante/inválido/expirado/reutilizado antes de persistir tokens

### Tiering runtime (Basic / Pro / Enterprise)
- Base canónica en DB:
  - `billing_plans`
  - `plan_capabilities`
  - `tenant_subscriptions`
  - `tenant_usage_counters`
  - `tenant_usage_events`
- Enforcement backend activo por capability/cuota vía RPC:
  - `consume_tenant_capability(...)`
- Endpoint de snapshot para operación/UX:
  - `GET /api/v1/settings/plan-capabilities`
- Existing tenants del entorno linked bootstrappeados a `enterprise` para no cortar operación live.

### Hardening observability + maintenance
- Eventos de seguridad API persistidos en `api_security_events`:
  - `rate_limit.exceeded`
  - `idempotency.replay`
  - `idempotency.payload_mismatch`
  - `idempotency.in_flight_conflict`
  - `idempotency.duplicate_conflict`
- Limpieza de `idempotency_keys` expiradas:
  - RPC: `cleanup_expired_idempotency_keys(...)`
  - endpoint owner-only: `POST /api/v1/settings/maintenance/idempotency-cleanup`
  - job automático en ai-orchestrator (interval configurable)

### Envia Fase 2 parcial (feature flag)
- Endpoints backend expuestos en `services/api/routers/shipping.py`:
  - `POST /api/v1/shipping/{shipment_id}/label`
  - `POST /api/v1/shipping/tracking`
  - `POST /api/v1/shipping/pickup`
  - `POST /api/v1/shipping/cancel`
- Guardados por `ENVIA_PHASE2_ENABLED` (default `false`).
- Frontend `/dashboard/shipping` ya integrado a Fase 2:
  - proxies Next: `POST /api/shipping/{shipmentId}/label|tracking|pickup|cancel`
  - bloque post-cotización para generar label, consultar tracking, agendar pickup y cancelar envío
  - mensaje explícito cuando backend responde `503` por feature flag desactivado

---

## Infra activa (Render)

| Servicio | URL | Estado |
|---|---|---|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | worker en web service (`/health`) | ✅ Live |

Supabase proyecto: `***SUPABASE_PROJECT_REF_REDACTED***`

---

## Env vars por servicio (modelo actual)

### `commerce-ops-connector`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `META_APP_SECRET`
- `META_VERIFY_TOKEN`
- `ALLOWED_ORIGINS`

### `commerce-ops-api`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `ALLOWED_ORIGINS`
- `MELI_CLIENT_ID`
- `MELI_CLIENT_SECRET`
- `MELI_REDIRECT_URI`
- `MELI_AUTH_URL`
- `MELI_OAUTH_STATE_SECRET`
- `MELI_OAUTH_STATE_TTL_SECONDS`
- `PLAN_ENFORCEMENT_ENABLED`
- `ENVIA_PHASE2_ENABLED`

### `commerce-ops-orchestrator`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `POLL_INTERVAL_SECONDS`
- `MAX_PROCESSING_ATTEMPTS`
- `CONVERSATION_HISTORY_LIMIT`
- `HUMAN_TAKEOVER_QUEUE_ENABLED`
- `HUMAN_TAKEOVER_QUEUE_POLL_BATCH`
- `HUMAN_TAKEOVER_QUEUE_VT_SECONDS`
- `WHATSAPP_OUTBOUND_QUEUE_ENABLED`
- `WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH`
- `WHATSAPP_OUTBOUND_QUEUE_VT_SECONDS`
- `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`
- `IDEMPOTENCY_CLEANUP_ENABLED`
- `IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS`
- `IDEMPOTENCY_CLEANUP_BATCH`

### `commerce-ops-web`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `APP_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `API_URL`

Notas:
- `META_ACCESS_TOKEN` y `WHATSAPP_PHONE_ID` no viven en env vars de servicios.
- Esas credenciales son por tenant en DB (`tenant_integrations`).

---

## Seguridad multi-tenant (modelo honesto)

- El backend usa `service_role` en paths críticos.
- `service_role` puede bypassar RLS.
- El aislamiento real depende de:
  1. filtro explícito `tenant_id` en queries sensibles
  2. RLS donde aplica

No asumir que frontend o RLS por sí solos aíslan cuando se usa `service_role`.

---

## Migraciones recientes (cierre correctivo)

- `20260419000000_conversation_processing_contract.sql`
  - normaliza estados de conversación legacy
  - impone constraint canónico de estados
  - agrega contrato explícito de procesamiento de mensajes

- `20260419000001_rbac_operator_runtime_only.sql`
  - backfill `agent -> operator`
  - impone constraint runtime (`owner|manager|operator`)

- `20260419000002_meli_oauth_state_store.sql`
  - tabla `integration_oauth_states` para nonce OAuth one-time

- `20260420000002_api_hardening_and_contacts_legal.sql`
  - `idempotency_keys` + extensión legal de `contacts`

- `20260420000003_human_takeover_notifications_queue.sql`
  - habilita `pgmq` (Supabase Queues)
  - trigger DB para encolar eventos de takeover
  - wrappers `dequeue/ack` para consumers backend

- `20260420000004_whatsapp_outbound_queue.sql`
  - cola durable outbound humano `whatsapp_outbound_messages`
  - wrappers `enqueue/dequeue/ack` para consumer backend

- `20260420000005_plan_tiering_foundation.sql`
  - foundation de planes/capabilities/subscriptions/usage
  - RPC enforcement (`consume_tenant_capability`) y snapshot (`get_tenant_plan_capabilities`)

- `20260420000006_api_security_observability.sql`
  - tabla `api_security_events`
  - RPC `cleanup_expired_idempotency_keys(...)`

---

## Operación rápida

Aplicar SQL:

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

Smoke tests usados en este cierre:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node --test apps/web/tests/marketplace-badges.test.mjs
pnpm --filter web lint
```

---

## Pendientes operativos reales

- SMTP propio (cuando exista dominio)
- Alerting/observabilidad operacional centralizada
- Envia Fase 2: validaciones carrier-específicas + webhooks async de tracking

El backlog funcional/técnico vive en `.context/04-next-steps.md`.
