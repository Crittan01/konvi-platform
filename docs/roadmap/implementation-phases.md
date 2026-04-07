# Fases de Implementación — Commerce Ops Platform

## Estado Global (Abril 2026)

| Fase | Nombre | Estado | Actualizado |
|---|---|---|---|
| 1 | Base Monorepo | ✅ Completa | 2026-04-05 |
| 2 | Auth y RLS | ✅ Completa | 2026-04-06 |
| 3a | Backoffice Web (Dashboard + Catálogo) | ✅ Completa | 2026-04-06 |
| 3b | Ciclo Conversacional Basic (Webhook → DB) | ✅ Completa | **2026-04-07** |
| **4** | **AI Orchestrator (Gemini → WhatsApp)** | **✅ Código completo** | **2026-04-07** |
| 5 | Inbox AI en Dashboard (Realtime) | ✅ Completa | **2026-04-07** |
| 6 | API Gateway real (`services/api`) | 🟡 Pendiente | — |
| 7 | Deploy en Render | ❌ Pendiente | — |
| 8 | Integración Mercado Libre | ❌ Pendiente | — |
| 9 | Shopify / Tienda custom | ❌ Futuro | — |

---

## Fase 1 — Base Monorepo ✅

- pnpm workspaces configurado
- Estructura de directorios: `apps/`, `services/`, `packages/`, `docs/`, `.agents/`
- `.gitignore` correcto (excluye `node_modules/`, `.next/`, `.venv/`, `.env`)
- `AGENTS.md` y reglas en `.agents/rules/`

## Fase 2 — Auth y RLS ✅

- Supabase Cloud provisionado: `xmelwnhhphksbpdjmbbp`
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
- ~~BLOQUEANTE: Tenant resolver usa `limit(1)`~~ → **RESUELTO 2026-04-07**: `db_persistence.py` refactorizado, resuelve por `meta_waba_id` + `status=active`
- `meta_waba_id = 2159052118202272` configurado en tenant ✅
- Migración `messages.processed` + índice parcial aplicada en Supabase ✅

## Fase 4 — AI Orchestrator ✅ (Código completo, pendiente deploy)

**Objetivo**: Ciclo completo mensaje → Gemini → respuesta WhatsApp

### Sub-tareas

- [x] **Fix Bloqueante**: `db_persistence.py` — resolver tenant por `meta_waba_id` (2026-04-07)
- [x] **Migración SQL**: columna `processed` + índice parcial en `messages` (2026-04-07)
- [x] **`worker.py`**: Loop polling (batch 10 msgs, `POLL_INTERVAL_SECONDS` configurable)
- [x] **`orchestrator.py`**: Context builder (catálogo + historial) + Gemini JSON mode + Pydantic
- [x] **`guardrails.py`**: confidence ≥ 0.65, texto no-nulo, longitud ≤ 1000 chars, human escalation
- [x] **`whatsapp_sender.py`**: POST Meta Graph API v21.0 via httpx async
- [x] **`tools/catalog_tool.py`**: Query productos activos del tenant (contexto LLM)
- [ ] **`GEMINI_API_KEY`**: Configurar en `.env` para activar el worker
- [ ] **Deploy en Render**: Como Background Worker (Fase 7)

**Decisión tomada**: Polling activo sobre `messages` (procesados=False), no Realtime.

## Fase 5 — Inbox AI Dashboard ✅ (Completa 2026-04-07)

- `apps/web/app/dashboard/inbox/page.tsx` — lista de conversaciones del tenant ✅
- Hilo de mensajes inbound/outbound con bubble UI ✅
- Suscripción Realtime para mensajes nuevos en la conversación activa ✅
- Suscripción Realtime para cambios en lista de conversaciones ✅
- Botón "Tomar control humano" / "Volver al bot" (cambia `status`) ✅

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
