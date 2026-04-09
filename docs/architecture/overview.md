# Arquitectura del Sistema — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Visión General

Plataforma SaaS multi-tenant de operaciones e-commerce conversacionales.
Los clientes (tenants) venden por WhatsApp. El sistema centraliza catálogo, pedidos, conversaciones, shipping e integraciones con aislamiento total de datos por tenant (RLS en PostgreSQL).

El LLM (Gemini) asiste en respuestas conversacionales pero **nunca es fuente de verdad** de stock, precios, pedidos ni estados transaccionales.

---

## Stack técnico — versiones reales en repo

| Capa | Versión real (verificada) | Objetivo |
|------|--------------------------|---------|
| Frontend | Next.js **14.1.0**, React ^18, TypeScript ^5 | Next.js 15.x |
| UI | TailwindCSS ^3.3.0, 5 componentes shadcn/ui en `apps/web/components/ui/` | Componentes en `packages/ui` |
| Backend HTTP | Python **3.9.25** (VM, EOL), FastAPI 0.128.8 | Python 3.11+ |
| DB / Auth | Supabase PostgreSQL, RLS, Auth, Realtime | — |
| IA | Google Gemini API (`gemini-2.5-flash`, `google-genai==1.47.0`) | — |
| Canal cliente | WhatsApp Cloud API (Meta oficial v21.0) | — |
| Canal interno | Telegram Bot API | Pendiente — alertas internas |
| Marketplace | Mercado Libre API | Fase 8 — pendiente |
| Marketplace futuro | Shopify Storefront API | Sin fecha |
| Shipping | Envia Shipping API + Queries API | 📋 Diseñado — no implementado |
| Hosting | Render — Web Services + Background Workers | Plan Starter antes de producción |
| Monorepo | pnpm workspaces | — |

> Fuente de verdad de versiones: `apps/web/package.json` y `services/*/requirements.txt`.
> Las versiones "Objetivo" son aspiracionales. No actualizar automáticamente sin validar impacto en Render.

---

## Componentes del sistema

### `apps/web` — Frontend (Tenant Console)

- **Responsabilidad**: Panel de operaciones para cada tenant
- **Rutas activas**:
  - `/login` — Auth Supabase SSR
  - `/dashboard` — Resumen del tenant
  - `/dashboard/catalog` — CRUD de productos (Server Actions)
  - `/dashboard/inbox` — Conversaciones WhatsApp con Realtime, human takeover
- **Rutas pendientes**: media, inventory, orders, contacts, knowledge-base, integrations, shipping, metrics, audit, settings
- **Platform Console**: No existe en código todavía
- **Seguridad**: `middleware.ts` protege `/dashboard/*`, redirige a `/login`
- **Auth SSR**: `@supabase/ssr` via `utils/supabase/server.ts`

### `services/connector-whatsapp` — Webhook Gateway Meta

- **Responsabilidad**: Recibir eventos de WhatsApp y encolar de forma asíncrona
- **Patrón**: Fire-and-forget — responde HTTP 200 en milisegundos, procesa en Background Task
- **Endpoints**:
  - `GET /api/v1/whatsapp/webhook` — Verificación del challenge de Meta
  - `POST /api/v1/whatsapp/webhook` — Recepción de mensajes (HMAC-SHA256 validado)
- **Estado**: ✅ Funcional. Tenant resolver por `meta_waba_id` real. HMAC validado.
- **URL Render**: `https://commerce-ops-connector.onrender.com`

### `services/ai-orchestrator` — Worker AI Asíncrono

- **Responsabilidad**: Ciclo completo de procesamiento de mensajes entrantes
- **Patrón**: Web Service en Render — `server.py` lanza FastAPI (`/health`, `/status`) + worker asyncio en thread daemon
- **Entry point Render**: `uvicorn server:app`
- **Flujo**:
  ```
  Poll messages (processed=False, direction=inbound) → cada 3s
    → Build context (catálogo del tenant + historial conversación)
    → Call Gemini API (JSON mode) → OrchestratorOutput Pydantic
    → Guardrails: confidence ≥ 0.65, texto no vacío, longitud ≤ 1000 chars, escalación humana
    → IF valid → POST Meta Graph API v21.0 (send message)
    → INSERT message(outbound) + UPDATE processed=True + processed_at (UTC)
  ```
- **Estado**: ✅ Implementado y live. Modelo activo: `gemini-2.5-flash` (billing habilitado).

### `services/api` — REST API Gateway

- **Responsabilidad**: API REST para el frontend. JWT Supabase validado. RBAC por endpoint (pendiente completar).
- **Endpoints activos**:
  - `GET /health`
  - `GET /api/v1/products` — Catálogo del tenant
  - `GET /api/v1/conversations` — Inbox paginado del tenant
- **Estado**: ✅ Live en Render. RBAC incompleto (riesgo R-09).
- **URL Render**: `https://commerce-ops-api.onrender.com`

### `services/connector-mercadolibre` — Pendiente (Fase 8)

- Sincronización de catálogo y pedidos con Mercado Libre API
- Estado: directorio vacío, sin implementación

### `services/connector-shopify` — Futuro

- Integración con Shopify Storefront y Admin API
- Sin fecha definida

### Shipping Connector (Envia) — Pendiente diseño de implementación

- Ver `docs/integrations/courier-envia.md` para diseño
- No existe como servicio todavía

---

## Esquema de Base de Datos (vigente)

```
tenants              — id, name, status, meta_waba_id, created_at
tenant_users         — id, user_id (→auth.users), tenant_id, role (owner/manager/agent)
products             — id, tenant_id, title, description, status, external_reference_id, is_active
product_variations   — id, product_id, tenant_id, price, stock_quantity, attributes (JSONB)
conversations        — id, tenant_id, customer_phone, status (bot_active/human_takeover/closed)
messages             — id, conversation_id, tenant_id, direction (inbound/outbound),
                       content_type, content, meta_message_id, processed (BOOL), processed_at
```

**Tablas pendientes de crear**: orders, order_items, contacts, shipments, kb_documents, audit_log, tenant_integrations.
Ver `docs/data/schema.md` para detalle.

---

## Seguridad Multi-Tenant

Ver `docs/architecture/multi-tenant-security.md` para contratos completos.

**Resumen**:
1. JWT del usuario contiene `app_metadata.tenant_id` (via trigger Supabase)
2. `app_current_tenant()` lee ese claim o `app.current_tenant_id` de la sesión Postgres
3. Todas las tablas con `tenant_id` tienen RLS con política `tenant_id = app_current_tenant()`
4. Workers usan `service_role` + `SET app.current_tenant_id = '<uuid>'` en cada query

---

## Flujo de mensaje WhatsApp (end-to-end)

```
Cliente WhatsApp
    │ envía mensaje
    ▼
Meta Graph API
    │ webhook POST
    ▼
services/connector-whatsapp
    │ valida HMAC-SHA256
    │ persiste mensaje (inbound, processed=False)
    │ responde HTTP 200 inmediatamente
    ▼
services/ai-orchestrator (polling cada 3s)
    │ lee mensajes processed=False
    │ construye contexto (catálogo + historial)
    │ llama Gemini (JSON mode)
    │ valida guardrails
    │ envía respuesta vía Meta Graph API v21.0
    │ persiste mensaje outbound
    └─ marca processed=True

apps/web/inbox
    └── Supabase Realtime → muestra hilos en tiempo real
```

---

## Diagrama de componentes

```
Meta Graph API v21.0 (WhatsApp Cloud API)
     │ webhooks entrantes (POST)
     ▼
┌─────────────────────────────────────────────────────┐
│         services/connector-whatsapp                 │  ✅ LIVE
│         (Webhook boundary — Meta)                   │
│  • Valida HMAC-SHA256                               │
│  • Resuelve tenant por meta_waba_id                 │
│  • Persiste mensaje (processed=False)               │
└──────────────────────┬──────────────────────────────┘
                       │ escribe en Supabase (service_role)
                       ▼
┌─────────────────────────────────────────────────────┐
│               SUPABASE (us-east-1)                  │
│  PostgreSQL + RLS + Auth + Realtime                 │
│  Proyecto: xmelwnhhphksbpdjmbbp                     │
└────┬──────────────────────┬──────────────────────┬──┘
     │ Supabase directo      │ Supabase directo     │ polling
     │ (Server Components /  │ (JWT validado)       │ (service_role)
     │  Server Actions /     │                      │
     │  Realtime SDK)        │                      │
     ▼                       ▼                      ▼
┌──────────────────┐  ┌──────────────┐  ┌─────────────────────────────┐
│  apps/web        │  │ services/api │  │  services/ai-orchestrator   │  ✅ LIVE
│  (Next.js 14.1)  │  │ (JWT Gateway)│  │  (Worker — polling 3s)      │
│  Tenant Console  │  │ ✅ LIVE      │  │  • Construye contexto        │
│  3/13 módulos    │  │              │  │  • Llama Gemini (JSON mode)  │
│  Platform Console│  └──────────────┘  │  • Valida guardrails         │
│  (pendiente)     │                    └──────────────┬──────────────┘
└──────────────────┘                                   │ httpx async
                                                       │ (mensajes salientes)
                                                       ▼
                                          Meta Graph API v21.0
                                          (respuestas al cliente)
```

> **Flujo crítico correcto**: El `ai-orchestrator` envía mensajes **directamente** a Meta API via `whatsapp_sender.py`.
> El `connector-whatsapp` **solo** maneja webhooks entrantes — no es intermediario de mensajes salientes.
> El `connector-whatsapp` nunca envía mensajes al cliente; solo recibe y persiste.

---

## Documentos relacionados

- `docs/architecture/modules.md` — Estado detallado de cada módulo
- `docs/architecture/multi-tenant-security.md` — Contratos RLS y RBAC
- `docs/architecture/connector-framework.md` — Framework de conectores
- `docs/architecture/async-processing.md` — Procesamiento asíncrono
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend
- `docs/product/current-scope.md` — Estado de implementación
