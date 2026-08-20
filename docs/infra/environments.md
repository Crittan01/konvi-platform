# Ambientes — konvi-platform

> Estado: VIGENTE · Última verificación contra código/infra: 2026-08-03 @ develop
>
> **Diseño canónico de la segregación integración-por-integración (Wompi, Meta, Aveonline, MeLi, Telegram, Resend, Gemini, Supabase):** [`environment-segregation.md`](environment-segregation.md) — qué credencial/URL/webhook usa cada ambiente y qué gaps faltan para la segregación total.
> **Plan de trabajo de segregación TOTAL (código + dashboards de plataformas, verificado contra doc oficial 2026-08-16):** [`environment-segregation-plan.md`](environment-segregation-plan.md).

## 1. Los tres ambientes que existen

| Ambiente | Qué es | Dónde vive | Quién escribe en él |
|---|---|---|---|
| **PROD** | La plataforma real | Render (4 servicios: `konvi-web`, `konvi-connector`, `konvi-api`, `konvi-orchestrator`) + Supabase cloud | Solo deploys desde la rama `production` y migraciones por protocolo seguro (§4) |
| **DEV local** | Desarrollo diario — **homologado a PRD desde S7 (2026-08-16)**: los 4 servicios corren con el MISMO entrypoint y el MISMO set de env vars por servicio que su contraparte Render (filtro fail-closed `scripts/dev_env_for_service.py`; certificación `bash scripts/certify_stg.sh` — 18 checks) | VM de desarrollo: apps locales (`.local/Makefile`, trackeado) + Supabase local en podman (`scripts/dbharness_up.sh`; Studio GUI en `http://127.0.0.1:54323`) | Desarrolladores/agentes, datos sintéticos |
| **CI** | Verificación | GitHub Actions: db-harness levanta Postgres con replay-desde-cero de las migraciones | Automático en cada push/PR |

**Regla de oro:** el desarrollo diario NO escribe en prod. Prod solo recibe: (a) código vía `git push origin develop:production`, (b) migraciones vía protocolo seguro, (c) flips de config explícitos del founder.

**Estado transitorio (pre-launch):** desde ENV-1 (2026-08-03) los scripts de testing corren por defecto contra el Supabase local (`.env.local` → `127.0.0.1`, clasifica `dev-safe`). El guard `scripts/_env_guard.py` mantiene el modo `prelaunch` para cuando alguien opera con credenciales de prod (`.env.prd-backup`): corren, pero avisan por stderr en cada ejecución contra qué proyecto escriben. El día del lanzamiento real, `LAUNCHED = True` en ese archivo los vuelve fail-closed contra prod. Este es el único acoplamiento dev↔prod que queda, y tiene fecha de muerte.

## 2. Segregación decidida (2026-08-03)

1. **ENV-1 — DEV local por defecto contra Supabase local (podman).** ✅ **CERRADO 2026-08-03.** `.env` y `apps/web/.env.local` apuntan a `http://127.0.0.1:54321` (DB `postgresql://postgres:postgres@127.0.0.1:54322/postgres`, `SUPABASE_PROJECT_REF=konvi-platform`, keys demo públicas del CLI vía `supabase status`); stack completo con `supabase start` (Studio `:54323`, Mailpit `:54324`); seeds sintéticos aplicados con `scripts/db/bootstrap_dev_sandbox.py` (tenant `KAIU Dev (sandbox)` + owners `dev-owner@konvi.test` / `visual-qa@konvi-qa.test`, creados vía Admin API de GoTrue local; password sintético solo-local: `konvi-dev-local-2026`). Cambios de código que lo habilitaron: `_env_guard.py` trata un `SUPABASE_PROJECT_REF` sin forma de ref cloud (slug local) como neutro (tests en `tests/test_env_guard.py`); `services/api/main.py` acepta `http://` solo en loopback en su validación de arranque. Evidencia smoke: REST `:54321` lista el tenant sandbox; supabase-py leyendo `.env` clasifica `dev-safe`; `pnpm --filter web dev` sirve `/login` 200 sin errores Supabase; `services/api` `/health` + `/health/ready` 200 contra la DB local. Limitaciones honestas: Meta/Wompi no llaman a localhost (se prueba con replay de payloads), Auth/Realtime sin paridad total con cloud. **Volver a prod:** `cp .env.pre-env1 .env.local && cp apps/web/.env.local.pre-env1 apps/web/.env.local` (respaldos locales gitignored tomados el 2026-08-03) o reconstruir desde `.env.prd-backup`; los respaldos restauran el estado exacto pre-ENV-1 — verificado que no hay otro archivo de config con credenciales cloud fuera de esos dos.
2. **Día del lanzamiento real — dev cloud.** Recrear un proyecto Supabase dev en org Free separada para UAT con webhooks reales: `scripts/db/replay_migrations_dev.sh` + `scripts/db/bootstrap_dev_sandbox.py` (~10 min) + `KONVI_SAFE_REFS=<ref>`. Trackeado: `docs/PLAN.md` §A #16.
3. **Meta Test App para STG (S2, 2026-08-19):** Test App `KAIU Chat - Test` (App ID `912826941411258`, hija de la app prod, modo Development permanente) + WABA de prueba `2159052118202272` + número de prueba `990364080831295` (+1 555-158-4034). Webhook verificado contra el connector STG vía ngrok (verify token per-tenant del tenant sandbox `d0000000-…-0001`; app secret + access token en el Vault local — el token actual es **temporal de ~24h**, reemplazar por System User token permanente de la Test App). La WABA de prueba tiene además suscritas las apps de prod (`KAIU Chat`, `Konvi App`) — **higiene pendiente [F]:** desuscribirlas para que el tráfico de prueba no se duplique hacia PRD.
4. **PROD** sin cambios: Render + Supabase cloud.

## 3. Convenciones vigentes

- **Ramas:** `develop` (integración, CI verde obligatorio) → `production` (deploy target; Render `autoDeploy` la observa). No existe `main`.
- **Servicios Render:** `konvi-<rol>` × 4. Multi-tenant real: N tenants = siempre los mismos 4 servicios; agregar un tenant son datos (`provision_tenant.py`), no un deploy.
- **Credenciales:** `.env.local` (dev) y `.env.prd-backup` (backup de prod, operación explícita), ambos gitignored. Convención 2026-08-14: 2 canónicos (local + prd-backup) + `apps/web/.env.local` (Next lo exige) + `.env.example` (contrato). Los scripts destructivos validan el target con `scripts/_env_guard.py` (deny-by-default; override auditable `KONVI_ALLOW_PROD=1`).
- **Costos de referencia** (verificar antes de cambiar planes): Supabase Pro ~$25/mes + Render 3× Starter ~$21/mes. DEV local: $0. Dev cloud futuro: $0 en org Free (pausa tras 1 semana inactivo; reanudación manual en el dashboard).
- **Rotación de credenciales por ambiente (decisión 2026-08-14):** solo **PRD** se rota (runbook `docs/operations/runbooks/credential-rotation.md`). **STG local NO se rota**: usa las keys demo públicas del Supabase CLI (no son secretas — las documenta Supabase) y solo tiene datos sintéticos → nada que mitigar. Lo que protege STG no es la rotación sino la **segregación** (`_env_guard.py` + ENV-1: STG nunca escribe en PRD). **Excepción futura:** el dev cloud del lanzamiento (#16, PLAN §A) SÍ tendrá keys reales → entra en la política de rotación.

## 4. Migraciones entre ambientes (regla)

1. Toda migración nace en dev y se valida con replay: `supabase db reset` debe terminar exit 0.
2. Schema puro replay-clean: seeds tenant-específicos con guard de existencia (`IF NOT EXISTS ... THEN RETURN; END IF;`); datos sintéticos NUNCA en migraciones (van en seeds de dev).
3. Aplicar a prod: `supabase db query --linked -f <migración>` → verificar → `supabase migration repair --status applied <ts>`.
4. Toda migración que altere schema o grants viaja en el mismo commit con `tests/dbharness/schema_baseline.sql` regenerado (`bash scripts/schema_drift_check.sh --update`) y `pytest tests/dbharness` verde en local (lección 2026-08-03: el gate `--ci` local no incluye db-harness; sin esto el CI falla en GitHub).
5. **Interlock migrate-before-deploy:** si un release toca DB, la migración se aplica a prod ANTES de pushear el código a `production`.

## 5. Branch protection (decisión vigente)

Se mantiene push-to-deploy directo a `production` (opción simple, un solo dev). Cuando entre un segundo desarrollador o Platform Console vaya live: migrar a PR-a-`production` con branch protection (FF-only + required-CI).
