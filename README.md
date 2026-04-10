# Commerce Ops Platform

> Plataforma SaaS Multi-Tenant de operaciones e-commerce conversacionales vía WhatsApp.

## Qué es este producto

**El producto NO es un bot.** Es un centro de operaciones e-commerce conversacional donde:

- WhatsApp (Meta Cloud API oficial) es el canal principal con el cliente final
- El catálogo, pedidos, inventario y reglas viven en el core del sistema
- El LLM (Gemini) es una capa de asistencia controlada — nunca fuente de verdad de datos
- Los conectores con marketplaces y servicios externos son módulos desacoplados
- El tenant opera su negocio desde la **Tenant Console**
- El dueño de la plataforma opera el SaaS desde la **Platform Console** (consola separada, aún no implementada)

## Estado Actual (2026-04-10)

**Fases 1-11 completadas.** Fase 12 (Platform Console) pendiente.

| Componente | Estado |
|---|---|
| Supabase Cloud (`***SUPABASE_PROJECT_REF_REDACTED***`) | ✅ Activo — 13 migraciones aplicadas |
| RLS + Custom Claims JWT | ✅ Implementados |
| Frontend — Tenant Console (13/13 módulos) | ✅ Live en Render |
| WhatsApp Connector | ✅ Live — HMAC validado, tenant resolver real |
| AI Orchestrator | ✅ Live — polling 3s, gemini-2.5-flash, KB inyectada |
| API Gateway | ✅ Live — JWT real, RBAC base, 8 routers |
| Meta Webhook | ✅ Configurado — E2E WhatsApp ↔ Gemini ↔ Inbox confirmado |
| Platform Console | ❌ Pendiente — Fase 12 (bloqueante: OQ-P01) |

> Ver `AGENTS.md` para el estado completo del sistema y `docs/HANDOFF.md` para próximos pasos.

## Stack Técnico

| Capa | Versión real | Notas |
|------|-------------|-------|
| Frontend | **Next.js 14.2.35**, React ^18, TypeScript ^5 | App Router, Server Actions |
| UI | TailwindCSS ^3.3.0, shadcn/ui (5 componentes) | Dark Warm Theme |
| Backend | **Python 3.9.25** (EOL), FastAPI 0.128.8 | VM Oracle Linux 9 |
| DB / Auth | Supabase PostgreSQL + RLS + Auth + Realtime | |
| IA | Google Gemini API (`gemini-2.5-flash`, `google-genai==1.47.0`) | |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) | |
| Shipping | Envia API — Fase Inicial operativa (quote + historial) | Label/tracking: Fase 2 |
| Hosting | Render — 4 servicios (Free plan) | Upgrade a Starter antes de producción |

> Fuente de verdad de versiones: `apps/web/package.json` y `services/*/requirements.txt`.

## Dos Consolas Separadas

| Consola | Para quién | Estado |
|---------|-----------|--------|
| **Tenant Console** (`/dashboard/*`) | El cliente/tenant — opera su negocio | ✅ 13/13 módulos implementados |
| **Platform Console** (`/platform/*`) | El dueño de la plataforma / superadmin | ❌ No implementada (Fase 12) |

No mezclar. No unificar. Separación estricta de layout, auth y permisos.

## Estructura del Monorepo

```
apps/
  web/                     # Frontend Next.js — Tenant Console ✅ LIVE
services/
  connector-whatsapp/      # Webhook Gateway Meta ✅ LIVE
  ai-orchestrator/         # Worker AI asíncrono ✅ LIVE
  api/                     # REST API Gateway ✅ LIVE
  connector-mercadolibre/  # ❌ Pendiente Fase 10 (conector backend)
packages/
  auth/                    # Wrappers SSR Supabase Auth (parcial)
  db/                      # Mirrors iniciales de migraciones (fuente real: supabase/migrations/)
  ui/                      # ❌ Vacío (componentes en apps/web/components/ui/)
docs/                      # Documentación completa
.agents/                   # Reglas y workflows para AI agents
supabase/migrations/       # 13 migraciones SQL aplicadas en producción
```

## Comandos Frecuentes

```bash
# Frontend dev
pnpm --filter web dev

# Build de verificación
cd apps/web && pnpm build

# Aplicar migración SQL
supabase db query --linked -f supabase/migrations/archivo.sql
# (psql directo NO funciona — Supavisor bloquea TCP)

# AI Orchestrator local
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py
```

## Documentación — Leer antes de tocar código

| Documento | Propósito |
|-----------|-----------|
| `AGENTS.md` | **Estado del sistema vigente** — leer primero |
| `docs/HANDOFF.md` | Estado actual y próximos pasos |
| `docs/product/current-scope.md` | Estado real de implementación verificado en código |
| `docs/product/admin-ui-modules.md` | Módulos de ambas consolas con estado |
| `docs/architecture/overview.md` | Arquitectura técnica del sistema |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño del módulo Shipping/Courier |
| `docs/roadmap/implementation-phases.md` | Fases 1-13 con estado real |
| `docs/risks/open-questions.md` | Preguntas abiertas y bloqueantes |
