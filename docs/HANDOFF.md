# Handoff — Estado Operativo Real (2026-07-12, rev. 112)

Este documento describe el estado operativo real de `develop` (= `production`).
Para árbol funcional y semántica de dominio: `.context/00-product.md`.
Para estado por módulo: `.context/01-state.md` (rev.112 = tabla bloques 0→H).
Los documentos de `docs/deployment/` y parte de `docs/operations/` contienen
histórico de fases previas; ante conflicto, este HANDOFF y `.context/01-state.md`
tienen prioridad.

---

## Actualización rev. 112 (2026-07-12) — iniciativa production-grade bloques 0→H DESPLEGADA

**Lo más reciente (tiene prioridad sobre el histórico de abajo):**

- **Topología de ramas (CORREGIDO):** el deploy target es la rama **`production`**
  (autodeploy on-push). Hoy `origin/production` == `origin/develop` == `0dbf1180`
  (PR #53). `main` está **249 commits ATRÁS** — NO es deploy target ni está a la par de
  develop. `develop` es la rama de integración; los PRs de cada bloque van a develop y
  luego se despliega con `git push origin origin/develop:production`. Los 4 servicios
  `konvi-*` corren el código actual.
- **Deploy:** los bloques 0→H de la iniciativa production-grade (PRs #26..#53, ADRs
  0032-0038) están EN PRODUCCIÓN (múltiples deploys jul-2026). Ver `.context/01-state.md`
  rev.112 para la tabla completa.
- **Migraciones:** **218 archivos** en `supabase/migrations/` (rango
  `20260406181235_initial_schema` … `20260712040000_g_shipment_status_monotonic`; 57
  nuevas en jul-2026). Cuántas están aplicadas a prod requiere query a
  `supabase_migrations.schema_migrations` (no verificable desde el repo). Protocolo:
  smoke ROLLBACK → apply → `supabase migration repair --status applied <ts>`.
- **`TENANT_HARD_DELETE_ENABLED`:** ya está `"true"` en `render.yaml` (el worker cron de
  hard-delete Fase 2 está habilitado en el blueprint desplegado).
- **CI:** `.github/workflows/ci.yml` corre `bash scripts/validate.sh --ci` en cada push
  a main + PRs. **Pre-deploy correr `--ci` local (NO `--build`)** — `--ci` añade ruff
  (baseline `BASELINE_RUFF_ERRORS=202`, actual 145), pytest obligatorio, coverage
  (`COVERAGE_MIN`, actual ~61%), warns→fails. CI workflow instala `pytest`
  (sin él cae a unittest discover → errores espurios). Runner del repo asume
  checkout en `/home/ansible/workspaces/konvi-platform` (symlink compat en ci.yml —
  deuda: ~187 tests con path absoluto, fix portable pendiente).
- **Reconciliación Wompi:** validado contra docs oficiales — el API público NO permite
  buscar transacción por payment_link_id/reference → cron automático INFACTIBLE.
  Mitigación: reintentos de webhook Wompi (30m/3h/24h) + runbook manual
  `docs/operations/runbooks/wompi-payment-reconciliation.md`.

---

## Resumen ejecutivo

- Tenant Console: ✅ live (fases 1–11.5 completas)
- Platform Console: ❌ fuera de alcance (bloqueante OQ-P01)
- Servicios live en Render: `web`, `connector-whatsapp`, `api`, `ai-orchestrator`
- DB canónica: `supabase/migrations/` (218 migraciones)
- **Habeas Data Ley 1581 end-to-end**: ✅ rev. 93–100 — audit logs append-only,
  SAR endpoint, retention policies per-tenant, PII tokenization aditiva,
  click-wrap acceptance, Resend notifications con fallback graceful.
- **Fase C Inbox (pagos Wompi)**: ✅ implementada y validada en sandbox (2026-04-24)

## Migraciones recientes (rev. 93–100)

| Timestamp | Archivo | Propósito |
|---|---|---|
| 20260502010000 | `consent_audit_log.sql` | Append-only audit Art. 9 |
| 20260502010001 | `pii_access_log.sql` | Trazabilidad de accesos PII |
| 20260505010000 | `retention_policies.sql` | TTL declarativos + pg_cron |
| 20260506010000 | `pii_tokenization.sql` | Hash + last4 de document_number |
| 20260507010000 | `tenant_legal_acceptance.sql` | Click-wrap DPA / privacy |
| 20260508010000 | `retention_per_tenant_fix.sql` | Fix rev. 100: itera per-tenant |

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
| `konvi-web` | `https://konvi-web.onrender.com` | ✅ Live |
| `konvi-connector` | `https://konvi-connector.onrender.com` | ✅ Live |
| `konvi-api` | `https://konvi-api.onrender.com` | ✅ Live |
| `konvi-orchestrator` | worker en web service (`/health`) | ✅ Live |

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

- `20260614110000_webhook_secrets_cron_cleanup.sql` ✅ APLICADA 2026-05-29
  - función `fn_cleanup_webhook_secrets()` cierra item F.10 del Plan K
  - invocada hourly desde `services/ai-orchestrator/worker.py` (patrón canónico,
    igual a `cleanup_expired_meli_webhook_dedup`)
  - limpia `previous_secret_hash` + `grace_period_until` post-grace en
    `tenant_webhook_secrets` (NULL out, no delete row)
  - GRANT EXECUTE solo a service_role; REVOKE de authenticated/anon

- `20260616000000_tenant_offboarding.sql` ✅ APLICADA 2026-05-29
  - J.2.4.4 Fase 1 — Tenant offboarding workflow (soft-delete + 30d grace)
  - Columnas `deletion_*` en `tenants`, tabla `tenant_offboarding_log` append-only
  - 3 RPCs SECURITY DEFINER: `fn_log_tenant_offboarding_event`,
    `fn_request_tenant_deletion`, `fn_cancel_tenant_deletion`

- `20260617000000_tenant_offboarding_phase2.sql` ✅ APLICADA 2026-05-29
  - J.2.4.4 Fase 2 — Hard-delete + cold archive
  - Storage bucket `offboarding-archive` (private, 50MB max, RLS service_role-only)
  - 2 RPCs SECURITY DEFINER: `fn_hard_delete_tenant`, `fn_list_tenants_pending_hard_delete`
  - Worker cron en `services/ai-orchestrator/worker.py` invoca hourly (DESACTIVADO
    por default — habilitar con `TENANT_HARD_DELETE_ENABLED=true` en Render env
    tras validar Fase 2 en staging)
  - Habeas Data Ley 1581 Art. 16 + Art. 22 cumplimiento

---

## Operación rápida

Aplicar SQL:

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

Gate pre-deploy (= comando exacto del CI):

```bash
bash scripts/validate.sh --ci   # pytest ~3490 + ruff + coverage + TS + build + tenant lint
```

Runner de tests (rev. 111): **pytest** (`python3.11 -m pytest tests/ -q`). El
`unittest discover` quedó como fallback — enmascaraba fallos cross-test que pytest
detecta; el CI DEBE tener pytest instalado.

---

## Pendientes operativos reales

- SMTP propio (cuando exista dominio)
- Alerting/observabilidad operacional centralizada
- Aveonline: webhooks async de tracking + polling backup (provider único shipping, ADR-0019)

Nota rev. 109: Envia eliminado del runtime (pivote ADR-0019). Tag git
`archive/envia-investigacion-rev106-2026-05-08` preserva investigación
histórica. Para Courier N+1 ver [`docs/adr/0023-shipping-provider-integration-pattern.md`](adr/0023-shipping-provider-integration-pattern.md).

El backlog funcional/técnico vive en `.context/04-next-steps.md`.
