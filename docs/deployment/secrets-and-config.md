# Secrets y Configuración (vigente)

Última actualización: 2026-04-21

## Reglas

1. `.env` nunca al repositorio.
2. `sync: false` en `render.yaml` implica carga manual en Render.
3. No documentar secretos reales; solo nombres de variables.

## Variables por servicio (runtime actual)

### `commerce-ops-web`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `APP_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `API_URL`
- `NEXT_PUBLIC_API_URL` (compat legacy opcional, no recomendado para nuevos paths server-side)

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
- `API_RATE_LIMIT_WRITE_PER_MINUTE` (opcional)
- `API_RATE_LIMIT_SEND_PER_MINUTE` (opcional)

### `commerce-ops-orchestrator`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `POLL_INTERVAL_SECONDS`
- `MAX_PROCESSING_ATTEMPTS`
- `CONVERSATION_HISTORY_LIMIT`
- `HUMAN_TAKEOVER_QUEUE_*`
- `WHATSAPP_OUTBOUND_QUEUE_*`
- `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`
- `IDEMPOTENCY_CLEANUP_*`

## Aclaración crítica WhatsApp

- API y orchestrator no usan `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` como fallback global para envío.
- Las credenciales outbound viven por tenant en `tenant_integrations`.

## Criterio de pago

Mover a planes pagos cuando estemos cerca de salida productiva o ante bloqueo operacional real en Free.
