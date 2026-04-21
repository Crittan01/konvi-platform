# Secrets y Configuración (vigente)

Última actualización: 2026-04-21

## Reglas

1. `.env` nunca al repositorio.
2. `sync: false` en `render.yaml` implica carga manual en Render.
3. No documentar secretos reales; solo nombres de variables.
4. Fuente canónica de servicios productivos: `render.yaml`.
5. `.env.example` es contrato local de desarrollo y scripts.

## Contrato por servicio (runtime)

### `commerce-ops-web`
- Requeridas:
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `APP_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `API_URL`
- Opcional:
  - `NEXT_PUBLIC_API_URL` (compat legacy, deprecada)

### `commerce-ops-connector`
- Requeridas:
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `META_APP_SECRET`
  - `META_VERIFY_TOKEN`
  - `ALLOWED_ORIGINS`

### `commerce-ops-api`
- Requeridas:
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
  - `API_RATE_LIMIT_WRITE_PER_MINUTE`
  - `API_RATE_LIMIT_SEND_PER_MINUTE`

### `commerce-ops-orchestrator`
- Requeridas:
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

## Variables locales (no runtime Render)

- `DATABASE_URL`
- `SUPABASE_PROJECT_REF`
- `SUPABASE_DB_PASSWORD`
- `TEST_TENANT_ID`
- `TEST_CATEGORY_ID`

Estas se usan para CLI/scripts locales, no para servicios live de Render.

## Aclaración crítica WhatsApp

- API y orchestrator no usan `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` como fallback global para envío.
- Las credenciales outbound viven por tenant en `tenant_integrations`.

## Criterio de pago

Mover a planes pagos cuando estemos cerca de salida productiva o ante bloqueo operacional real en Free.
