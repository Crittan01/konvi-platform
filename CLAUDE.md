# CLAUDE.md — Konvi Platform

Contexto rápido para desarrollo.  
No sustituye el código ni la jerarquía documental de `.context/`.

## Estado

- Tenant Console: fases `1-11.5` completadas (live).
- Platform Console: fase `12` bloqueada por `OQ-P01` (fuera de alcance actual).
- Servicios activos en Render: `web`, `connector-whatsapp`, `api`, `ai-orchestrator`.

## Stack real (repo)

| Capa | Versión |
|---|---|
| Frontend | Next.js `15.5.20` + React `^19` + TypeScript `^5` |
| Backend Python | FastAPI `0.128.8`, Pydantic `2.12.5`, `supabase==2.28.3` |
| IA | `google-genai==1.47.0`; modelo prod `gemini-3.1-flash-lite` (render.yaml), default código `gemini-3.5-flash`, cascade a `claude-sonnet-4-5` rescue |
| DB/Auth | Supabase PostgreSQL + RLS + Auth + Realtime |
| Mensajería | WhatsApp Cloud API oficial (`v22.0`) |

## Estructura clave

```text
apps/web/                     # Tenant Console
services/api/                 # API Gateway
services/connector-whatsapp/  # Meta webhook inbound
services/ai-orchestrator/     # Worker AI + colas
supabase/migrations/          # fuente canónica de esquema
```

## Principios críticos

1. Multi-tenant real: toda operación atada a `tenant_id`.
2. El frontend no es seguridad.
3. `service_role` exige filtros explícitos por tenant.
4. El LLM no decide verdad transaccional.
5. WhatsApp: solo API oficial Meta.

## Leer en TODA sesión (obligatorio)

1. `.context/00-product.md` — árbol funcional, qué está en scope (135 líneas)
2. `.context/01-state.md`   — estado actual del sistema, últimas 3 sesiones (≈290 líneas)
3. `.context/02-stack.md`   — versiones reales del stack (50 líneas)
4. `.context/03-rules.md`   — reglas de implementación (34 líneas)
5. `.context/04-next-steps.md` — pendientes reales y backlog (≈160 líneas)

## Leer solo cuando la tarea lo requiera (on-demand)

- `.context/06-contracts.md` — contratos de runtime: estados de conversación, procesamiento, FSM Inbox, Wompi, Aveonline.
  Leer si tocas: Orchestrator, API, Connector, Worker, lógica de pedidos/pagos.
- `docs/HANDOFF.md` — estado operativo de infra Render + migraciones aplicadas.
  Leer si tocas: deployment, infra, migraciones pendientes.
- `.context/05-doc-policy.md` — política documental.
  Leer solo si actualizas documentación.
- `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md` — Konvi NUNCA será Partner Meta. Cada tenant Direct Provider con SU PROPIA Meta App + HMAC per-tenant.
  Leer si tocas: connector WhatsApp, integración Meta, onboarding tenants, webhook routing.
- `docs/adr/0024-invariant-binary-only-criterion.md` — Invariants en `apply_invariants` SOLO si verificación binaria/determinística (SET membership, DB lookup, comparación numérica). NO parsers NLP semánticos.
  Leer si tocas: agentic/invariants, validación post-LLM, anti-hallucination.
- `docs/adr/0025-multi-tenant-isolation-strategy.md` — Aislamiento = lint AST (`scripts/audit_tenant_filter.py`) + RLS GUC + Vault ownership. Patrón canónico `.table(X).eq("tenant_id", tid)`. Helper `scoped_table` ELIMINADO (0 adopción).
  Leer si tocas: queries DB multi-tenant, RLS, seguridad cross-tenant, webhooks.

## NO leer (reduce tokens ~50%)

- `supabase/migrations/` — 218 SQLs. Leer solo si hay tarea explícita de migración.
- `.context/01-state-archive.md` — historial de sesiones archivado.
- `packages/db/migrations/` — snapshot legacy divergido, no canónico.
- `scratch/`, `scripts/debug/` — temporales locales.
- `infra/render/`, `infra/local/`, `infra/supabase/` — vacíos.
- `services/connector-mercadolibre/`, `services/connector-shopify/`,
  `services/cron/`, `services/worker/` — solo README (Fase 13 futura).

## Leer si hay tarea de cumplimiento / cierre

- `docs/reports/rev93_99_habeas_data_completion.md` — cierre Habeas Data Ley 1581.
- `docs/reports/rev100_certification_closure.md` — cierre real certificación rev. 100.
- `docs/reports/rev102_habeas_data_ux_hardening.md` — UX/legal hardening + 5 bugs runtime.
- `docs/legal/*.md` — DPA, privacy, subprocessors, incident-response, roles.
- `docs/adr/0003-habeas-data-compliance-strategy.md` — decisiones + follow-ups F1-F11.

## Validación pre-deploy

```bash
bash scripts/validate.sh             # sintaxis + ~3490 tests (pytest) + tenant lint + TypeScript + ESLint
bash scripts/validate.sh --build     # + Next.js build (detecta errores que bloquean Render)
bash scripts/validate.sh --full      # + pip-audit + coherencia vars
bash scripts/validate.sh --coverage  # + cobertura Python (baseline 58.9%, target 70% Sem 11)
bash scripts/validate.sh --lint      # + ruff Python (baseline 202 errores, cleanup Sem 2-3)
bash scripts/validate.sh --ci        # CI strict: --full + --coverage + --build + warns→fails
```

CI/CD: `.github/workflows/ci.yml` ejecuta `validate.sh --ci` + Next.js build en cada PR.

Test runner: **pytest** (rev. 111 A6.2.5 — migrado de unittest discover que
enmascaraba 2 fallos cross-test). Fallback a unittest si pytest ausente.

Baselines:
- **Coverage Python**: 58.9% (target J.5 = 70% Sem 11) — env `COVERAGE_MIN=55` ajustable
- **ruff lint errors**: 202 baseline (cleanup planificado Sem 2-3) — env `BASELINE_RUFF_ERRORS=202`
- **Tenant filter gaps**: 0 baseline (A6.2.7 CERRADO — aislamiento multi-tenant completo) (ratchet decreciente) — env `BASELINE_MAX=0`. Lint AST `scripts/audit_tenant_filter.py` enforce `.eq("tenant_id", tid)` en queries multi-tenant (ADR-0025). A6.2.7 CERRADO: 198→0 gaps (BUG_REAL fix + EXEMPTION justificado + refactor signatures).

