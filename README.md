# Konvi Platform

SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp (B2B2C, foco Colombia).

## Estado actual (2026-04-21)

- Fases `1-11.5` de Tenant Console: completadas y live.
- Fase `12` (Platform Console): bloqueada por `OQ-P01` y fuera de alcance actual.
- Runtime activo: `web`, `connector-whatsapp`, `api`, `ai-orchestrator`.
- Esquema canónico DB: `supabase/migrations/` (42 migraciones en repo).

Fuente operativa principal:
- Estado real por módulo: `.context/01-state.md`
- Operación/infra: `docs/HANDOFF.md`

## Stack técnico real (repo)

| Capa | Estado |
|---|---|
| Frontend | Next.js `14.2.35`, React `^18`, TypeScript `^5` |
| Backend | FastAPI `0.128.8`, Pydantic `2.12.5`, `supabase==2.28.3` |
| IA | `google-genai==1.47.0`, modelo `gemini-2.5-flash` |
| DB/Auth | Supabase PostgreSQL + RLS + Auth + Realtime |
| Mensajería | WhatsApp Cloud API oficial (`v22.0`) |
| Hosting | Render (`render.yaml`) |

## Estructura del monorepo

```text
apps/web/                  # Tenant Console (Next.js)
services/api/              # API Gateway (FastAPI, 9 routers funcionales + marketplace)
services/connector-whatsapp/ # Webhook Meta inbound
services/ai-orchestrator/  # Worker AI + colas (modo web en Render Free)
packages/                  # Paquetes compartidos y/o deferred (ver docs/tech/monorepo-packages.md)
supabase/migrations/       # FUENTE CANÓNICA de esquema SQL
.context/                  # Contexto L1/L2 de producto, estado y reglas
docs/                      # Documentación técnica y operativa
```

## Comandos frecuentes

```bash
pnpm --filter web dev
python3.11 -m unittest discover -s tests -p 'test_*.py'
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## Documentación que sí manda

| Documento | Uso |
|---|---|
| `.context/00-product.md` | Tree funcional oficial (L1) |
| `.context/01-state.md` | Estado real implementado (L1) |
| `.context/04-next-steps.md` | Pendientes reales (L2) |
| `.context/05-doc-policy.md` | Política de consistencia documental |
| `docs/HANDOFF.md` | Operación live e infraestructura |
| `docs/deployment/render-upgrade-path.md` | Criterio para transición Free -> pago |
| `docs/tech/` | Hardening API, tiering y decisiones técnicas |
