# CLAUDE.md — Commerce Ops Platform

Contexto rápido para desarrollo.  
No sustituye el código ni la jerarquía documental de `.context/`.

## Estado

- Tenant Console: fases `1-11.5` completadas (live).
- Platform Console: fase `12` bloqueada por `OQ-P01` (fuera de alcance actual).
- Servicios activos en Render: `web`, `connector-whatsapp`, `api`, `ai-orchestrator`.

## Stack real (repo)

| Capa | Versión |
|---|---|
| Frontend | Next.js `14.2.35` + React `^18` + TypeScript `^5` |
| Backend Python | FastAPI `0.128.8`, Pydantic `2.12.5`, `supabase==2.28.3` |
| IA | `google-genai==1.47.0`, `gemini-2.5-flash` |
| DB/Auth | Supabase PostgreSQL + RLS + Auth + Realtime |
| Mensajería | WhatsApp Cloud API oficial (`v21.0`) |

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

- `.context/06-contracts.md` — contratos de runtime: estados de conversación, procesamiento, FSM Inbox, Wompi, Envia.
  Leer si tocas: Orchestrator, API, Connector, Worker, lógica de pedidos/pagos.
- `docs/HANDOFF.md` — estado operativo de infra Render + migraciones aplicadas.
  Leer si tocas: deployment, infra, migraciones pendientes.
- `.context/05-doc-policy.md` — política documental.
  Leer solo si actualizas documentación.

## NO leer (reduce tokens ~50%)

- `supabase/migrations/` — 87 SQLs. Leer solo si hay tarea explícita de migración.
- `.context/01-state-archive.md` — historial de sesiones archivado.
- `packages/db/migrations/` — snapshot legacy divergido, no canónico.
- `scratch/`, `scripts/debug/` — temporales locales.
- `infra/render/`, `infra/local/`, `infra/supabase/` — vacíos.
- `services/connector-mercadolibre/`, `services/connector-shopify/`,
  `services/cron/`, `services/worker/` — solo README (Fase 13 futura).

## Leer si hay tarea de cumplimiento / cierre

- `docs/reports/rev93_99_habeas_data_completion.md` — cierre Habeas Data Ley 1581.
- `docs/reports/rev100_certification_closure.md` — cierre real certificación rev. 100.
- `docs/legal/*.md` — DPA, privacy, subprocessors, incident-response, roles.
- `docs/adr/0003-habeas-data-compliance-strategy.md` — decisiones + follow-ups F1-F7.

## Validación pre-deploy

```bash
bash scripts/validate.sh          # sintaxis + 1167 tests + TypeScript + lint
bash scripts/validate.sh --full   # + pip-audit + coherencia vars
```

