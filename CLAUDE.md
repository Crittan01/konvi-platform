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

## Leer primero

1. `.context/00-product.md`
2. `.context/01-state.md`
3. `.context/04-next-steps.md`
4. `docs/HANDOFF.md`

