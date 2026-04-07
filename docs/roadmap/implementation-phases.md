# Fases de Implementación — Commerce Ops Platform

## Estado Global (Abril 2026)

| Fase | Nombre | Estado |
|---|---|---|
| 1 | Base Monorepo | ✅ Completa |
| 2 | Auth y RLS | ✅ Completa |
| 3a | Backoffice Web (Dashboard + Catálogo) | ✅ Completa |
| 3b | Ciclo Conversacional Basic (Webhook → DB) | 🟡 Parcial |
| **4** | **AI Orchestrator (Gemini → WhatsApp)** | **❌ En curso — PRIORIDAD** |
| 5 | Inbox AI en Dashboard (Realtime) | ❌ Pendiente |
| 6 | API Gateway real (`services/api`) | ❌ Pendiente |
| 7 | Deploy en Render | ❌ Pendiente |
| 8 | Integración Mercado Libre | ❌ Pendiente |
| 9 | Shopify / Tienda custom | ❌ Futuro |

---

## Fase 1 — Base Monorepo ✅

- pnpm workspaces configurado
- Estructura de directorios: `apps/`, `services/`, `packages/`, `docs/`, `.agents/`
- `.gitignore` correcto (excluye `node_modules/`, `.next/`, `.venv/`, `.env`)
- `AGENTS.md` y reglas en `.agents/rules/`

## Fase 2 — Auth y RLS ✅

- Supabase Cloud provisionado: `***SUPABASE_PROJECT_REF_REDACTED***`
- 5 migraciones SQL aplicadas:
  - `20260406181235` — Tenants + tenant_users
  - `20260406181236` — Catálogo (products, product_variations)
  - `20260406181237` — Conversaciones (conversations, messages)
  - `20260406181238` — RLS policies + `app_current_tenant()`
  - `20260406181239` — Custom claims trigger (JWT con tenant_id)
- `middleware.ts` SSR protege rutas `/dashboard`

## Fase 3a — Backoffice Web ✅

- Login funcional con Supabase Auth
- Dashboard: muestra email + tenant del usuario
- Catálogo: CRUD básico con Server Actions (Next.js)
- Layout con sidebar: Dashboard, Catálogo, Inbox (link)

## Fase 3b — Ciclo Conversacional Basic 🟡

- `connector-whatsapp` recibe webhooks de Meta
- Firma HMAC-SHA256 validada ✅
- Parser de payload WhatsApp ✅
- Persistencia en `conversations` y `messages` ✅
- **BLOQUEANTE**: Tenant resolver usa `limit(1)` — hardcode inadmisible para multi-tenant

## Fase 4 — AI Orchestrator ❌ (EN CURSO)

**Objetivo**: Ciclo completo mensaje → Gemini → respuesta WhatsApp

### Sub-tareas

- [ ] **Fix Bloqueante**: `db_persistence.py` — resolver tenant por `meta_waba_id`
- [ ] **Nueva migración SQL**: columna `processed` y `processed_at` en `messages`
- [ ] **`services/ai-orchestrator/worker.py`**: Loop de polling sobre mensajes no procesados
- [ ] **`services/ai-orchestrator/orchestrator.py`**: Context builder + llamada a Gemini
- [ ] **`services/ai-orchestrator/guardrails.py`**: Validación de output antes de enviar
- [ ] **`services/ai-orchestrator/whatsapp_sender.py`**: POST a Meta Graph API `/messages`
- [ ] **`services/ai-orchestrator/tools/catalog_tool.py`**: Query de productos del tenant

**Pregunta abierta**: ¿Polling activo o Supabase Realtime para detectar mensajes nuevos?

## Fase 5 — Inbox AI Dashboard ❌

- Página `/dashboard/inbox/page.tsx` — listar conversaciones del tenant
- Hilo de mensajes por conversación (inbound/outbound visual)
- Suscripción Realtime para mensajes nuevos
- Botón "Tomar control humano" (cambia `status` de la conversación)

## Fase 6 — API Gateway Real ❌

- `services/api` con lógica real (reemplaza mocks)
- Autorización por tenant en cada endpoint
- CORS restringido a dominios permitidos (env var `ALLOWED_ORIGINS`)

## Fase 7 — Deploy en Render ❌

- `render.yaml` en la raíz del monorepo
- 3 servicios: `connector-whatsapp` (Web), `ai-orchestrator` (Worker), `commerce-web` (Web)
- Variables de entorno en Render Dashboard (nunca en `.env` del repo)

## Fase 8 — Integración Mercado Libre ❌

- `services/connector-mercadolibre/`
- Sincronización de catálogo ML → tabla `products`
- Gestión de pedidos ML

## Fase 9 — Shopify / Tienda Custom (Futuro) ❌

- `services/connector-shopify/`
- Diseño modular via `connector-framework.md`

---

## Regla de Actualización

**Actualizar este archivo cada vez que una sub-tarea de una Fase sea completada.**
Mover el estado del módulo en `docs/architecture/modules.md` al mismo tiempo.
