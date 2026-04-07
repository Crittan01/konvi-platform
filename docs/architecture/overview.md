# Arquitectura del Sistema — Commerce Ops Platform

## Visión General

Plataforma SaaS Multi-Tenant conversacional que automatiza ventas e-commerce vía WhatsApp usando IA generativa (Gemini). Cada cliente es un **tenant** con aislamiento total de datos.

## Stack Técnico

| Capa | Tecnología | Justificación |
|---|---|---|
| Frontend | Next.js 15, React, TypeScript, TailwindCSS, shadcn/ui | App Router SSR, performance, ecosistema maduro |
| Backend HTTP | Python 3.11+, FastAPI | Async nativo, tipado, compatible con Pydantic AI |
| DB / Auth | Supabase PostgreSQL, RLS, Auth, Realtime | Multi-tenant real con RLS, Auth integrado |
| IA | Google Gemini API (gemini-1.5-flash/pro), output estructurado Pydantic | LLM con control de salida tipada |
| Canal cliente | WhatsApp Cloud API (Meta oficial) | Único canal oficial aprobado |
| Canal interno | Telegram Bot API | Notificaciones y alertas internas |
| Marketplace inicial | Mercado Libre API | Mayor volumen LATAM |
| Marketplace futuro | Shopify Storefront API | Expansión a tienda propia |
| Hosting | Render — Web Services + Background Workers | CD automático, sin DevOps complejo |
| Monorepo | pnpm workspaces | Gestión de paquetes compartidos |

## Módulos del Sistema

### `apps/web` — Frontend Backoffice

- **Responsabilidad**: Panel de administración para operadores de cada tenant
- **Rutas activas**:
  - `/login` — Auth con Supabase SSR
  - `/dashboard` — Resumen (tenant + usuario)
  - `/dashboard/catalog` — CRUD de productos con Server Actions
  - `/dashboard/inbox` — [EN IMPL.] Bandeja de conversaciones WhatsApp con Realtime
- **Seguridad**: `middleware.ts` protege todas las rutas `/dashboard`, redirige a `/login`
- **Auth SSR**: `@supabase/ssr` via `utils/supabase/server.ts`

### `services/connector-whatsapp` — Webhook Gateway Meta

- **Responsabilidad**: Recibir eventos de WhatsApp y encolarlos asíncronamente
- **Patrón**: Fire-and-forget — responde HTTP 200 en milisegundos, procesa en background
- **Endpoints**:
  - `GET /api/v1/whatsapp/webhook` — Verificación del challenge de Meta
  - `POST /api/v1/whatsapp/webhook` — Recepción de mensajes (con validación HMAC-SHA256)
- **Estado**: Funcional. **BLOQUEANTE: tenant resolver usa `limit(1)` hardcodeado**
- **Fix requerido**: Resolver tenant por `meta_waba_id` del payload

### `services/ai-orchestrator` — Worker AI Asíncrono

- **Responsabilidad**: Ciclo completo de procesamiento de mensajes entrantes
- **Patrón**: Background Worker en Render (sin HTTP entry point publico)
- **Flujo**:
  ```
  Poll messages(processed=False, direction=inbound)
    → Build context (tenant products + conversation history)
    → Call Gemini API → OrchestratorOutput(Pydantic)
    → Guardrail validation (confidence ≥ 0.7)
    → IF valid → send via Meta API + persist outbound message
    → Mark message processed=True
  ```
- **Estado**: ❌ Solo README. Es el módulo prioritario a implementar.

### `services/api` — REST API Interna

- **Responsabilidad**: Capa de API Gateway para el frontend (reemplazar llamadas directas a Supabase)
- **Endpoints planificados**:
  - `GET /api/v1/products` — Catálogo del tenant (con RLS via service role)
  - `GET /api/v1/conversations` — Inbox paginado
- **Estado**: Esqueleto con mocks. Implementar después del Orchestrator.

### `packages/auth` — Wrappers Supabase Auth SSR

- Funciones server-side para leer sesión y tenant desde JWT custom claims
- Estado: directorio con README, sin implementación completa

### `packages/db` — Esquemas y Helpers RLS

- Tipos TypeScript generados de Supabase
- Helpers para set_config de tenant_id en queries backend
- Estado: directorio con README, sin implementación completa

## Esquema de Base de Datos

```
tenants           — id, name, status, meta_waba_id, created_at
tenant_users      — id, user_id (→auth.users), tenant_id, role (owner/manager/agent)
products          — id, tenant_id, title, description, status
product_variations — id, product_id, tenant_id, price, stock_quantity, attributes (JSONB)
conversations     — id, tenant_id, customer_phone, status (bot_active/human_takeover/closed)
messages          — id, conversation_id, tenant_id, direction (inbound/outbound),
                    content_type, content, meta_message_id, processed (BOOL), processed_at
```

## Seguridad Multi-Tenant

Ver `docs/architecture/multi-tenant-security.md` para contratos detallados.

**Resumen**:
1. JWT del usuario contiene `app_metadata.tenant_id` (vía Trigger de Supabase)
2. `app_current_tenant()` lee ese claim o el `app.current_tenant_id` en la sesión Postgres
3. Todas las tablas con `tenant_id` tienen RLS activado con política `tenant_id = app_current_tenant()`
4. Backend workers usan `service_role` + `set app.current_tenant_id = '...'` en cada query
