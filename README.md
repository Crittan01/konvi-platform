# Commerce Ops Platform

> Plataforma SaaS Multi-Tenant para operación e-commerce conversacional vía WhatsApp.

## Estado Actual (Abril 2026)

**Fase activa**: Implementación del ciclo conversacional completo (AI Orchestrator).

| Componente | Estado |
|---|---|
| Supabase Cloud (`xmelwnhhphksbpdjmbbp`) | ✅ Provisionado |
| Migraciones SQL (5 archivos) | ✅ Aplicadas |
| RLS + Custom Claims JWT | ✅ Definidos |
| Frontend Next.js (`apps/web`) | ✅ Funcional — Auth, Dashboard, Catálogo |
| WhatsApp Webhook (`connector-whatsapp`) | 🟡 Parcial — falta fix de tenant resolver |
| AI Orchestrator (`ai-orchestrator`) | ❌ En implementación |
| Inbox AI en Dashboard | ❌ En implementación |
| Deploy en Render | ❌ Pendiente |

## Stack Técnico

- **Frontend**: Next.js 15, React, TypeScript, TailwindCSS, shadcn/ui
- **Backend**: Python 3.11+, FastAPI, uvicorn
- **DB / Auth / Storage**: Supabase (PostgreSQL, RLS, Auth, Realtime)
- **IA**: Google Gemini API
- **Mensajería Cliente**: WhatsApp Cloud API (Meta)
- **Hosting**: Render (Web Services + Background Workers)
- **Monorepo**: pnpm workspaces

## Estructura del Monorepo

```
apps/web/                    # Frontend Next.js — Backoffice
services/
  connector-whatsapp/        # Webhook Gateway Meta (FastAPI)
  ai-orchestrator/           # Worker AI asíncrono (Python)
  api/                       # REST API interna (FastAPI)
  connector-mercadolibre/    # [Futuro]
  connector-shopify/         # [Futuro]
packages/
  auth/                      # Wrappers SSR Supabase Auth
  db/                        # Esquemas y helpers RLS
supabase/migrations/         # 5 migraciones SQL aplicadas
docs/                        # Documentación completa del sistema
.agents/                     # Reglas y workflows para AI agents
```

## Variables de Entorno Requeridas

Ver `.env.example`. Las variables productivas se configuran como **Secrets en Render**, nunca en el repositorio.

## Comandos Frecuentes

```bash
# Frontend dev
pnpm --filter web dev

# WhatsApp connector dev
cd services/connector-whatsapp && uvicorn main:app --reload --port 8000

# Orquestador worker
cd services/ai-orchestrator && python main.py

# Aplicar migraciones Supabase
supabase db push
```

## Documentación

- `docs/architecture/` — Módulos, stack, RLS, conectores
- `docs/roadmap/` — Fases e hitos
- `docs/setup/` — Configuración manual de Supabase y Meta
- `docs/deployment/` — Guía de despliegue en Render
- `.agents/rules/` — Reglas obligatorias para AI agents
- `.agents/workflows/` — Workflows de desarrollo y operación
