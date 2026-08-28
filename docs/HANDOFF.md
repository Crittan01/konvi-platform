# HANDOFF — Operación de Konvi Platform

> Estado: VIGENTE · Última verificación: 2026-08-03 @ develop

Puerta operativa del repo: qué está live, cómo se opera y dónde vive cada fuente de verdad.
Sin secciones históricas — la historia está en git y en `docs/_archive/`.

---

## 1. Qué está live

**Render** (plan Starter, región Oregon, `autoDeploy` sobre la rama `production`, blueprint `render.yaml`):

| Servicio | rootDir | Rol |
|---|---|---|
| `konvi-web` | `apps/web` | Tenant Console (Next.js 16) |
| `konvi-connector` | `services/connector-whatsapp` | Webhook gateway Meta, Model B per-tenant |
| `konvi-api` | `services/api` | Core API REST (28 routers `/api/v1`) |
| `konvi-orchestrator` | `services/ai-orchestrator` | Worker IA (polling inbound, FSM agentic, outbound, 19 crons; daemon thread dentro del web service) |

**Supabase cloud** (proyecto productivo único): PostgreSQL + RLS + Auth + Vault + pgmq — 251 migraciones aplicadas, 79 tablas live. Credenciales: `.env.prd-backup` (backup de las plataformas integradas) y Render Dashboard (nunca en repo).

**Estado infra (2026-08-27, Track 3):** los 3 servicios Python pineados a `PYTHON_VERSION=3.13.15` vía Render API (deploys live verificados: `/health` 200 ×4 servicios + log "Using Python version 3.13.15 via environment variable"; compat probada por el gate CI `py-compat-313` — suite completa bajo CPython 3.13.15) · custom domain `api.konvi.co` creado en `konvi-api` (`unverified` hasta que exista el CNAME — pasos exactos en `docs/deployment/domains-and-subdomains.md`; el subdominio onrender sigue activo, webhooks sin corte) · G8b cerrado: media legada del inbox migrada al bucket privado `tenant-inbox-media` (1 objeto, `messages.media_url` re-apuntado, URL pública vieja cerrada) · environment "Production" del project Konvi: protection pendiente [F] (solo Admin desde Dashboard — 4 clicks documentados en PLAN-CIERRE §Track 3).

Multi-tenant real: N tenants = los mismos 4 servicios; agregar un tenant son datos (`scripts/admin/provision_tenant.py`, runbook `docs/operations/onboarding-tenants.md`), no un deploy.

## 2. Ramas y deploy

- **`develop`** = integración (PRs + CI verde obligatorio). **`production`** = deploy target. **No existe `main`**.
- Estado hoy (verificado con git): `develop` == `origin/develop` (`a66d45f7`, CI verde #30778777844); `origin/production` = `5fdad396`, 8 commits atrás — la promoción es decisión del founder (`docs/PLAN.md` §E).
- **Desplegar:** gate local verde → `git push origin origin/develop:production` → Render redespliega los servicios cuyos archivos cambiaron → smoke checks (`/health` de los 4, Inbox, shipping quote).
- **Rollback** de código y de esquema: `docs/deployment/rollout-and-rollback.md`.
- Si el release toca DB: la migración se aplica a prod **antes** de pushear el código a `production` (interlock migrate-before-deploy, `docs/infra/environments.md` §4).

## 3. Operación frecuente

```bash
# Aplicar SQL a prod (psql TCP bloqueado por Supavisor — todo va por la CLI)
supabase db query --linked -f archivo.sql

# Gate pre-deploy (= comando exacto del CI; NO usar --build)
bash scripts/validate.sh --ci    # ruff + pytest + coverage (gate 60) + TS + build + tenant lint

# Tests
python3.11 -m pytest tests/ -q -m 'not dbharness' -n auto   # suite unidad (4.336 tests en total, 201 de ellos dbharness)
bash scripts/validate.sh --db-harness                        # 201 tests vs Postgres real (scripts/dbharness_up.sh)
pnpm --filter web test                                       # Vitest (33 archivos)
```

CI (`.github/workflows/ci.yml`): jobs `validate` (validate.sh), `py-core` (pins de prod api+orchestrator), `db-harness` (replay-desde-cero + baseline), `build-web`. Nota: el gate local `--ci` **no** incluye db-harness — si tocas schema/grants, corre `pytest tests/dbharness` en local antes de pushear.

Ambientes (dev local podman, guard prelaunch, segregación): `docs/infra/environments.md`.

## 4. Migraciones

- **251 archivos** en `supabase/migrations/` = ledger de prod. Nunca editar una migración aplicada: la reversión es una migración compensatoria nueva.
- **Protocolo:** smoke `BEGIN; … ROLLBACK;` → `supabase db query --linked -f <migración>` (una por vez) → verificar → `supabase migration repair --status applied <timestamp>`.
- Toda migración que altere schema o grants viaja en el mismo commit con `tests/dbharness/schema_baseline.sql` regenerado (`bash scripts/schema_drift_check.sh --update`).

## 5. Seguridad multi-tenant (modelo honesto)

- Los 3 servicios Python usan **`service_role`**, que **bypasea RLS**.
- El aislamiento real depende de: (1) filtro explícito `tenant_id` en queries, enforced por lint AST (`scripts/audit_tenant_filter.py`, gate `--max-gaps 0` en CI); (2) RLS como última barrera donde aplica; (3) secretos de tenants en Supabase Vault.
- El frontend no es una barrera de seguridad. No asumir que RLS sola aísla en paths de `service_role`.
- Detalle: `docs/architecture/multi-tenant-security.md`, `docs/backend/BACKEND.md` §3, ADR-0025.

## 6. Pendientes operativos

El checklist go-live (B1-B6 + flips founder), el backlog priorizado y los rituales viven en **`docs/PLAN.md`** (§A, §B, §D). No se duplican aquí.

> **⚠️ Deadline Meta 2026-09-30 (Track 6, doc oficial):** cada WABA de tenant necesita **método de pago registrado** antes de esa fecha — desde 2026-10-01 los service messages (free-form en ventana 24h: TODO el tráfico del bot/operadores) se cobran, y una WABA sin método de pago **deja de recibir mensajes**. Acción founder/ops por tenant (WhatsApp Manager → WABA → Payment method). Detalle: `docs/integrations/whatsapp-meta.md` §Alineación doc oficial.

> **Nota CLI Supabase:** la VM quedó pineada a **2.90.0** a propósito (2026-08-22): la 2.115.0 siembra default privileges distintos en el replay local (MAINTAIN-only a roles de cliente) y rompe la homologación STG↔PRD + el formato del dump del baseline. El bump de CLI/imagen PG es un track separado que exige evaluar la versión de prod cloud primero.

> **DR — root key de Vault (Track 6, 2026-08-22):** un restore manual de la DB a un proyecto Supabase NUEVO (pg_dump o clonado) **NO porta la root key de pgsodium** → todos los secretos de tenants en Vault quedan ilegibles. Antes de un restore a proyecto nuevo, portar la root key vía Management API: `GET /v1/projects/{ref}/pgsodium` (origen) → `PUT /v1/projects/{ref}/pgsodium` (destino) ([doc oficial](https://supabase.com/docs/guides/database/vault) §key-portability). Después, re-verificar con un `SELECT count(*) FROM vault.decrypted_secrets` (si descifra, la key viajó).

## 7. Fuente de verdad por tema

| Tema | Doc |
|---|---|
| Qué es el producto / módulos | `docs/product/PRD.md` · `.context/00-product.md` |
| Qué falta (backlog, go-live) | `docs/PLAN.md` |
| Estado por módulo | `.context/01-state.md` |
| Stack, NFR, CI/CD | `docs/tech/TRD.md` |
| Backend (servicios, routers, worker, testing) | `docs/backend/BACKEND.md` |
| Bot conversacional (dispatcher, FSM, tools, invariants) | `.context/09-bot-flowchart.md` · `docs/architecture/agentic.md` |
| Flujos end-to-end (venta, pago, despacho, takeover, onboarding) | `docs/flows/` |
| Integraciones (Wompi, Aveonline, Meta, MeLi, Telegram) | `docs/integrations/` |
| Ambientes y migraciones entre ambientes | `docs/infra/environments.md` |
| Contratos runtime extendidos | `.context/06-contracts.md` |
| UX/UI (design system Kaiu) | `docs/ux/UX-UI.md` |
| Decisiones arquitectónicas (histórico por diseño) | `docs/adr/` |
