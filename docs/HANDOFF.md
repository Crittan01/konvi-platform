# Handoff — Estado Operativo Real (2026-04-24, rev. 31)

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
- DB canónica: `supabase/migrations/` (49 migraciones)
- **Fase C Inbox (pagos Wompi)**: ✅ implementada y validada en sandbox (2026-04-24)

## Cierre de auditoría (2026-04-21)

- `scripts/test-mass-import.mjs` ya no contiene key hardcodeada; usa `SUPABASE_SERVICE_ROLE_KEY` por entorno.
- `origin` local saneado sin token embebido en URL.
- Inbox (`status` y `send`) consolidado vía proxies Next server-side (`/api/conversations/...`).
- Arquitectura `packages/` normalizada en estado mínimo/deferred (ver `packages/README.md` y `docs/tech/monorepo-packages.md`).
- Contrato de entorno congelado y alineado entre `.env.example`, `render.yaml` y docs de deployment.

---

## Contratos runtime vigentes

> Movidos a `.context/06-contracts.md` (lectura on-demand — solo cuando se toca Orchestrator/API/Worker).
> Resumen operativo rápido: estados conversación (`bot_active | human_takeover | closed`),
> mensajes con `processing_status`, WhatsApp por tenant_integrations (sin env vars),
> Wompi Fase C activa en sandbox.

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

## Env vars por servicio

> Referencia canónica: `.env.example` (con etiquetas `[RENDER]` / `[LOCAL]` / `[DB]`).
> Blueprint de Render: `render.yaml`.

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

- `20260422150000_conversations_last_interaction_sync.sql`
  - backfill de `conversations.last_interaction_at` desde `messages.created_at`
  - trigger DB para mantener recencia de Inbox consistente en nuevos mensajes

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
