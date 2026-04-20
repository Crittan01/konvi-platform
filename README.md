# Commerce Ops Platform

> SaaS Multi-Tenant de operaciones e-commerce conversacionales vía WhatsApp.

## Qué es este producto

**El producto NO es un bot.** Es un centro de operaciones e-commerce conversacional donde:

- WhatsApp Cloud API (Meta oficial) es el canal principal con el cliente final
- El catálogo, pedidos, inventario y reglas viven en el core del sistema
- El LLM (Gemini) es asistencia controlada — nunca fuente de verdad de datos
- Los conectores con marketplaces y servicios externos son módulos desacoplados
- El tenant opera su negocio desde la **Tenant Console**
- La **Platform Console** (administración SaaS) es frontera futura — no implementada

## Estado (2026-04-19 — rev. 26)

**Fases 1-11.5 completadas** (incl. Reclamos, Compras, Finanzas, Marketplace). Fase 12 (Platform Console) bloqueada por OQ-P01.

| Componente | Estado |
|---|---|
| Tenant Console | ✅ Live — 18 módulos, Route Groups, RBAC, flujo invite validado |
| WhatsApp Connector | ✅ Live — HMAC validado, tenant resolver real |
| AI Orchestrator | ✅ Live — polling 3s, gemini-2.5-flash, KB + pgvector inyectada |
| API Gateway | ✅ Live — JWT, RBAC, 9 routers |
| Supabase Cloud | ✅ Activo — 35 migraciones aplicadas |
| Platform Console | ❌ No implementada — Fase 12, bloqueante OQ-P01 |

> Ver estado completo por módulo → `.context/01-state.md`
> Ver infra y credenciales → `docs/HANDOFF.md`

## Stack Técnico

| Capa | Versión real |
|---|---|
| Frontend | **Next.js 14.2.35**, React ^18, TypeScript ^5 |
| UI | TailwindCSS ^3.3.0, shadcn/ui (11 componentes) — Dark Warm Theme |
| Backend | **Python 3.11.13**, FastAPI 0.128.8 |
| DB / Auth | Supabase PostgreSQL + RLS + Auth + Realtime |
| IA | `gemini-2.5-flash` via `google-genai==1.47.0` |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) |
| Shipping | Envia API — Fase Inicial live (quote + historial) |
| Hosting | Render — 4 servicios (Free plan) |

> Fuente de verdad de versiones: `apps/web/package.json` y `services/*/requirements.txt`.

## Estructura del Monorepo

```
apps/
  web/                     # Frontend Next.js — Tenant Console ✅ LIVE
services/
  connector-whatsapp/      # Webhook Gateway Meta ✅ LIVE
  ai-orchestrator/         # Worker AI asíncrono ✅ LIVE
  api/                     # REST API Gateway ✅ LIVE
packages/
  auth/                    # Wrappers SSR Supabase Auth (parcial)
  db/                      # Mirrors parciales de migraciones (fuente real: supabase/migrations/)
supabase/migrations/       # 35 migraciones SQL — FUENTE CANÓNICA del esquema
.context/                  # Contexto activo del sistema — leer primero
.agents/                   # Reglas y workflows para AI agents
docs/                      # Documentación técnica detallada
```

## Comandos Frecuentes

```bash
# Frontend dev
pnpm --filter web dev

# Aplicar migración SQL
supabase db query --linked -f supabase/migrations/archivo.sql

# AI Orchestrator local
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py
```

## Documentación — Leer antes de tocar código

| Documento | Propósito |
|---|---|
| `.context/00-product.md` | **Tree Funcional vigente** — leer siempre antes de crear o mover UI |
| `.context/01-state.md` | Estado real de implementación verificado en código |
| `.context/04-next-steps.md` | Próximos pasos y deuda técnica |
| `.context/05-doc-policy.md` | **Política documental** — jerarquía y reglas de consistencia |
| `AGENTS.md` | Quick context para agentes IA |
| `docs/HANDOFF.md` | Estado operativo, credenciales, lecciones |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño del módulo Shipping/Courier |
| `docs/risks/open-questions.md` | Preguntas abiertas y bloqueantes |
