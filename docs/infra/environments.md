# Ambientes — konvi-platform

> Estado: VIGENTE · Última verificación contra código/infra: 2026-08-03 @ develop

## 1. Los tres ambientes que existen

| Ambiente | Qué es | Dónde vive | Quién escribe en él |
|---|---|---|---|
| **PROD** | La plataforma real | Render (4 servicios: `konvi-web`, `konvi-connector`, `konvi-api`, `konvi-orchestrator`) + Supabase cloud | Solo deploys desde la rama `production` y migraciones por protocolo seguro (§4) |
| **DEV local** | Desarrollo diario | VM de desarrollo: apps locales + Supabase local en podman (`scripts/dbharness_up.sh`; Studio GUI en `http://127.0.0.1:54323`) | Desarrolladores/agentes, datos sintéticos |
| **CI** | Verificación | GitHub Actions: db-harness levanta Postgres con replay-desde-cero de las migraciones | Automático en cada push/PR |

**Regla de oro:** el desarrollo diario NO escribe en prod. Prod solo recibe: (a) código vía `git push origin develop:production`, (b) migraciones vía protocolo seguro, (c) flips de config explícitos del founder.

**Estado transitorio (pre-launch):** hoy algunos scripts de testing corren contra prod bajo el guard `scripts/_env_guard.py` en modo `prelaunch` — corren, pero avisan por stderr en cada ejecución contra qué proyecto escriben. El día del lanzamiento real, `LAUNCHED = True` en ese archivo los vuelve fail-closed contra prod. Este es el único acoplamiento dev↔prod que queda, y tiene fecha de muerte.

## 2. Segregación decidida (2026-08-03)

1. **ENV-1 — DEV local por defecto contra Supabase local (podman).** El stack ya existe y replica limpio las 251 migraciones; falta que las apps (web + servicios) apunten por defecto a `127.0.0.1:54321` (`.env` y `apps/web/.env.local`), con seeds sintéticos de `scripts/db/bootstrap_dev_sandbox.py`. Limitaciones honestas: Meta/Wompi no llaman a localhost (se prueba con replay de payloads), Auth/Realtime sin paridad total con cloud. Trackeado: `docs/PLAN.md` §B ENV-1.
2. **Día del lanzamiento real — dev cloud.** Recrear un proyecto Supabase dev en org Free separada para UAT con webhooks reales: `scripts/db/replay_migrations_dev.sh` + `scripts/db/bootstrap_dev_sandbox.py` (~10 min) + `KONVI_SAFE_REFS=<ref>`. Trackeado: `docs/PLAN.md` §A #16.
3. **PROD** sin cambios: Render + Supabase cloud.

## 3. Convenciones vigentes

- **Ramas:** `develop` (integración, CI verde obligatorio) → `production` (deploy target; Render `autoDeploy` la observa). No existe `main`.
- **Servicios Render:** `konvi-<rol>` × 4. Multi-tenant real: N tenants = siempre los mismos 4 servicios; agregar un tenant son datos (`provision_tenant.py`), no un deploy.
- **Credenciales:** `.env` (dev) y `.env.prod` (operación explícita de prod), ambos gitignored. Los scripts destructivos validan el target con `scripts/_env_guard.py` (deny-by-default; override auditable `KONVI_ALLOW_PROD=1`).
- **Costos de referencia** (verificar antes de cambiar planes): Supabase Pro ~$25/mes + Render 3× Starter ~$21/mes. DEV local: $0. Dev cloud futuro: $0 en org Free (pausa tras 1 semana inactivo; reanudación manual en el dashboard).

## 4. Migraciones entre ambientes (regla)

1. Toda migración nace en dev y se valida con replay: `supabase db reset` debe terminar exit 0.
2. Schema puro replay-clean: seeds tenant-específicos con guard de existencia (`IF NOT EXISTS ... THEN RETURN; END IF;`); datos sintéticos NUNCA en migraciones (van en seeds de dev).
3. Aplicar a prod: `supabase db query --linked -f <migración>` → verificar → `supabase migration repair --status applied <ts>`.
4. Toda migración que altere schema o grants viaja en el mismo commit con `tests/dbharness/schema_baseline.sql` regenerado (`bash scripts/schema_drift_check.sh --update`) y `pytest tests/dbharness` verde en local (lección 2026-08-03: el gate `--ci` local no incluye db-harness; sin esto el CI falla en GitHub).
5. **Interlock migrate-before-deploy:** si un release toca DB, la migración se aplica a prod ANTES de pushear el código a `production`.

## 5. Branch protection (decisión vigente)

Se mantiene push-to-deploy directo a `production` (opción simple, un solo dev). Cuando entre un segundo desarrollador o Platform Console vaya live: migrar a PR-a-`production` con branch protection (FF-only + required-CI).
