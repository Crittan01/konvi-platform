# Handoff — Estado Operativo Real (2026-04-19, rev. 23)

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
- DB canónica: `supabase/migrations/` (35 migraciones)

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

### `commerce-ops-orchestrator`
- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `POLL_INTERVAL_SECONDS`
- `MAX_PROCESSING_ATTEMPTS`
- `CONVERSATION_HISTORY_LIMIT`

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
- Envia Fase 2 (labels/tracking/pickup)

El backlog funcional/técnico vive en `.context/04-next-steps.md`.
