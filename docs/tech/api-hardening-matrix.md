# API Hardening Matrix (Tenant Console)

Fecha: 2026-04-20  
Ámbito: `services/api` (Tenant Console).  
Regla base: el frontend no es seguridad; el gateway API + RLS conforman defensa en capas.

## 1) Rate Limit por bucket

| Bucket | Endpoints | Límite default | Clave |
|---|---|---:|---|
| `write.default` | `POST/PATCH/DELETE` de `orders`, `contacts`, `shipping` | `120 req/min` | `bucket + tenant_id + client_ip` |
| `conversation.send` | `POST /api/v1/conversations/{id}/send` | `40 req/min` | `bucket + tenant_id + client_ip` |

Env vars:
- `API_RATE_LIMIT_ENABLED` (`true`/`false`)
- `API_RATE_LIMIT_WRITE_PER_MINUTE` (default `120`)
- `API_RATE_LIMIT_SEND_PER_MINUTE` (default `40`)

Headers de respuesta:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `Retry-After` (solo cuando responde `429`)

## 2) Idempotencia persistente

Tabla: `public.idempotency_keys`  
Scope canónico: `(tenant_id, idempotency_key, request_method, request_path)`

Comportamiento:
- Sin header `Idempotency-Key`: operación normal (sin replay).
- Reintento con misma key y mismo payload: replay de `status/body` persistido.
- Misma key con payload diferente: `409`.
- Misma key en ejecución concurrente: `409`.

Endpoints instrumentados:
- `POST /api/v1/orders/`
- `POST /api/v1/contacts/`
- `PATCH /api/v1/contacts/{contact_id}`
- `POST /api/v1/shipping/quote`
- `PATCH /api/v1/shipping/{shipment_id}/rate`
- `POST /api/v1/conversations/{conversation_id}/send`

## 3) Matriz de validaciones de input (gateway)

### Orders
- `status` query y patch: solo `pending|confirmed|processing|shipped|delivered|cancelled`.
- `items` mínimo 1.
- `title` item: `1..180`.
- `notes`: máximo `1200`.
- `shipping_cost`: `0..999999999`.
- `quantity`: `>=1`.
- `unit_price`: `>0`.

### Shipping
- `parcels` mínimo 1.
- Dimensiones y peso: `>0`.
- `content`: máximo `180`.
- Address fields acotados por longitud (`name`, `phone`, `street`, `city`, `state`, `postalCode`).
- Runtime CO:
  - DANE aceptado en 5 u 8 dígitos.
  - Shipping API usa DANE 8 dígitos en `city/postalCode`.

### Conversations
- `status`: solo contrato canónico (`bot_active|human_takeover|closed`).
- `send.text`:
  - no vacío
  - máximo `4096`
  - solo permitido cuando conversación está en `human_takeover`.

### Contacts
- `phone`: regex `^\+?[1-9]\d{7,19}$`.
- `name`: máximo `120`.
- `notes`: máximo `1200`.
- `consent_notice_version`: máximo `80`.
- `consent_revoked_reason`: máximo `500`.
- `consent_source`: conjunto cerrado:
  - `manual_console`
  - `whatsapp`
  - `web_form`
  - `phone_call`
  - `in_person`
  - `import`
  - `other`
- Si `consent_given=true`: `consent_source` requerido.

## 4) Contrato legal extendido de contactos

Campos nuevos en `contacts`:
- `consent_source`
- `consent_notice_version`
- `consent_evidence` (`jsonb`)
- `consent_actor_email`
- `consent_revoked_at`
- `consent_revoked_reason`

Objetivo operativo:
- evidenciar captura de autorización (canal, versión de aviso, actor, timestamp)
- soportar revocatoria trazable (fecha + motivo)

## 5) Consideraciones de operación

- El rate limit actual es en memoria por proceso (no distribuido entre réplicas).
- Limpieza de `idempotency_keys`:
  - automática en ai-orchestrator (`cleanup_expired_idempotency_keys`)
  - manual owner-only en `POST /api/v1/settings/maintenance/idempotency-cleanup`
- El cliente web debe enviar `Idempotency-Key` en acciones write críticas.

## 6) Enforcement por plan (Basic/Pro/Enterprise)

Base runtime:
- `PLAN_ENFORCEMENT_ENABLED=true`
- decisión en backend (no frontend) vía capability + cuota.

Capabilities endurecidas en API:
- `orders.create`
- `shipping.quote`
- `shipping.confirm_rate`
- `conversations.send`
- `integrations.mercadolibre`

Headers operativos:
- `X-Plan-Code`
- `X-Plan-Capability`
- `X-Plan-Limit` (si aplica)
- `X-Plan-Remaining` (si aplica)
- `X-Plan-Reset-At` (si aplica)
