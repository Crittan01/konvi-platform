# Commerce Ops Platform

> Plataforma SaaS Multi-Tenant de operaciones e-commerce conversacionales vía WhatsApp.

## Qué es este producto

**El producto NO es un bot.** Es un centro de operaciones e-commerce conversacional donde:

- WhatsApp (Meta Cloud API oficial) es el canal principal con el cliente final
- El catálogo, pedidos, inventario y reglas viven en el core del sistema
- El LLM (Gemini) es una capa de asistencia controlada — nunca fuente de verdad de datos
- Los conectores con marketplaces y servicios externos son módulos desacoplados
- El tenant opera su negocio desde la **Tenant Console**
- El dueño de la plataforma opera el SaaS desde la **Platform Console** (consola separada)

## Estado Actual (2026-04-09)

**Fase activa**: Fase 7 en progreso — 4 servicios live en Render, PASOS 6-7 pendientes de acción humana.

| Componente | Estado |
|---|---|
| Supabase Cloud (`xmelwnhhphksbpdjmbbp`) | ✅ Activo — 6 migraciones aplicadas |
| RLS + Custom Claims JWT | ✅ Implementados |
| Frontend (`apps/web`) — Auth, Dashboard, Catálogo, Inbox AI | ✅ Live en Render |
| WhatsApp Connector (`connector-whatsapp`) | ✅ Live — HMAC validado, tenant resolver real |
| AI Orchestrator (`ai-orchestrator`) | ✅ Live — polling 3s, gemini-2.5-flash, billing activo |
| API Gateway (`services/api`) | ✅ Live — JWT real, CRUD productos + conversaciones |
| Meta Webhook configurado | ⚠️ Pendiente — PASO 6 requiere acción humana |
| Test E2E WhatsApp → Gemini → Respuesta | ⚠️ Pendiente — PASO 7 requiere acción humana |
| META_ACCESS_TOKEN permanente | ⚠️ Pendiente — token temporal ~24h, migrar a System User Token (IH-006) |

> Ver `docs/HANDOFF.md` para el estado completo y `docs/operations/HUMAN_INTERVENTIONS.md` para pasos detallados.

## Stack Técnico (versiones reales en repo)

| Capa | Versión real | Objetivo futuro |
|------|-------------|-----------------|
| Frontend | **Next.js 14.1.0**, React ^18, TypeScript ^5 | Next.js 15.x |
| UI | TailwindCSS ^3.3.0, shadcn/ui (5 componentes) | Componentes en `packages/ui` |
| Backend | **Python 3.9.25** (VM, EOL), FastAPI 0.128.8 | Python 3.11+ |
| DB / Auth | Supabase PostgreSQL + RLS + Auth + Realtime | — |
| IA | Google Gemini API (`gemini-2.5-flash`, `google-genai==1.47.0`) | — |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) | — |
| Shipping | Envia Shipping API (📋 diseñado — no implementado) | — |
| Hosting | Render — 4 servicios (Free plan) | Plan Starter antes de producción |

> Fuente de verdad de versiones: `apps/web/package.json` y `services/*/requirements.txt`.

## Dos Consolas Separadas

| Consola | Para quién | Estado |
|---------|-----------|--------|
| **Tenant Console** (`/dashboard/*`) | El cliente/tenant — opera su negocio | 🟡 Parcial — 3/13 módulos |
| **Platform Console** (`/platform/*`) | El dueño de la plataforma / superadmin | ❌ No implementada |

No mezclar. No unificar. Separación estricta de layout, auth y permisos.

## Estructura del Monorepo

```
apps/
  web/                     # Frontend Next.js — Tenant Console (3/13 módulos)
services/
  connector-whatsapp/      # Webhook Gateway Meta ✅ LIVE
  ai-orchestrator/         # Worker AI asíncrono ✅ LIVE
  api/                     # REST API Gateway ✅ LIVE
  connector-mercadolibre/  # ❌ Pendiente Fase 8
  connector-shopify/       # ❌ Futuro
packages/
  auth/                    # Wrappers SSR Supabase Auth (parcial)
  db/                      # Migraciones SQL (6 aplicadas)
  ui/                      # ❌ Vacío (componentes en apps/web/components/ui/)
docs/                      # Documentación completa — leer antes de tocar código
.agents/                   # Reglas y workflows para AI agents
```

## Variables de Entorno

Ver `.env.example`. Las variables productivas se configuran en **Render Environment Variables** — nunca en el repositorio.

## Comandos Frecuentes

```bash
# Frontend dev
pnpm --filter web dev

# WhatsApp connector dev
cd services/connector-whatsapp && uvicorn main:app --reload --port 8000

# AI Orchestrator (local)
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py

# Aplicar migraciones Supabase
supabase db query --linked -f supabase/migrations/archivo.sql
# (psql directo NO funciona — Supavisor bloquea TCP)
```

## Documentación

Lee antes de tocar código:

| Documento | Propósito |
|-----------|-----------|
| `AGENTS.md` | **Estado del sistema vigente** — leer primero |
| `docs/HANDOFF.md` | Estado de la sesión actual y próximos pasos |
| `docs/product/current-scope.md` | Estado real de implementación verificado en código |
| `docs/product/admin-ui-modules.md` | Módulos de Tenant Console y Platform Console con estado |
| `docs/architecture/overview.md` | Arquitectura técnica del sistema |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend + orden de implementación |
| `docs/integrations/courier-envia.md` | Diseño del módulo Shipping/Courier (Envia) |
| `docs/operations/HUMAN_INTERVENTIONS.md` | Pasos manuales obligatorios (IH-001 a IH-006) |
| `docs/roadmap/implementation-phases.md` | Fases 1-12 con estado real |
| `.agents/rules/` | Reglas técnicas obligatorias para AI agents |
