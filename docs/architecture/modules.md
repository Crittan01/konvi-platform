# Módulos del Monorepo — Responsabilidades y Estado

## Estado Global (Abril 2026)

```
apps/web              ✅ Funcional (Auth, Dashboard, Catálogo)
services/
  connector-whatsapp  🟡 Parcial (tenant resolver hardcodeado)
  ai-orchestrator     ❌ En implementación — PRIORIDAD #1
  api                 🟡 Esqueleto con mocks
  connector-meli      ❌ Pendiente (Fase 4)
  connector-shopify   ❌ Pendiente (futuro)
packages/auth         🟡 Parcial
packages/db           🟡 Parcial
```

---

## 1. Aplicaciones (`apps/*`)

### `apps/web`

- **Responsabilidad:** Panel Backoffice para operadores de e-commerce. Permite gestionar catálogo, ver conversaciones y auditar respuestas de la IA.
- **Pila Técnica:** Next.js 15 (App Router), React, TailwindCSS, shadcn/ui, TypeScript.
- **Auth SSR:** `@supabase/ssr` via `middleware.ts` — protege todas las rutas `/dashboard`.
- **Rutas activas:**
  - `/login` — Formulario de autenticación con Supabase
  - `/dashboard` — Resumen de tenant y usuario autenticado
  - `/dashboard/catalog` — CRUD de productos (Server Actions)
  - `/dashboard/inbox` — [EN IMPL.] Bandeja de conversaciones con Realtime
- **Relaciones:** Consume Supabase directamente en Server Components. En el futuro, consumirá `services/api` para operaciones transaccionales complejas.

---

## 2. Servicios Backend (`services/*`)

### `services/connector-whatsapp`

- **Responsabilidad:** Boundary gateway para Meta. Recibe webhooks de WhatsApp, valida firma HMAC-SHA256, y delega el procesamiento a un Background Task.
- **Pila:** FastAPI (Python 3.11+), `python-supabase`.
- **Patrón:** Fire-and-forget — retorna HTTP 200 en milisegundos (política Meta).
- **Estado:** Funcional para recibir y persistir mensajes.
- **BLOQUEANTE #1:** `db_persistence.py` línea 37 usa `limit(1)` para resolver tenant. Debe buscar por `meta_waba_id`.

### `services/ai-orchestrator` ← **PRIORIDAD #1**

- **Responsabilidad:** Worker asíncrono. Lee mensajes no procesados, construye contexto del tenant, llama a Gemini, valida el output, y envía la respuesta por WhatsApp Cloud API.
- **Pila:** Python 3.11+, `google-generativeai`, `pydantic`, `supabase-py`.
- **Patrón Render:** Background Worker (no tiene HTTP entry point público).
- **Flujo:**
  ```
  Loop(polling cada 2s)
    → SELECT messages WHERE processed=False AND direction='inbound'
    → Obtener productos del tenant (catálogo para contexto)
    → Construir prompt con historial de conversación
    → Llamar Gemini → OrchestratorOutput pydantic
    → Guardrail: rechazar si confidence < 0.7
    → Enviar respuesta vía Meta API
    → INSERT message(outbound) + UPDATE processed=True
  ```
- **Estado:** Solo README. A implementar completamente.

### `services/api`

- **Responsabilidad:** REST API sincrónica para el Frontend. CRUD de catálogos y configuraciones, con autorización por tenant.
- **Pila:** FastAPI, `supabase-py` con `service_role`.
- **Estado:** Esqueleto. Routers vacíos con mocks.
- **Prioridad:** Implementar después del Orchestrator.

### `services/connector-mercadolibre` (Fase 4)

- **Responsabilidad:** Sincronización de catálogo y pedidos con MercadoLibre API.
- **Estado:** Directorio vacío. Pendiente.

### `services/connector-shopify` (Futuro)

- **Responsabilidad:** Integración con Shopify Storefront y Admin API.
- **Estado:** Directorio vacío. Pendiente.

---

## 3. Paquetes Compartidos (`packages/*`)

### `packages/auth`

- **Responsabilidad:** Wrappers SSR oficiales de Supabase Auth para Next.js. Custom claims JWT con `tenant_id`.
- **Estado:** README y package.json. Lógica dispersa en `apps/web/utils/supabase/`.

### `packages/db`

- **Responsabilidad:** Tipos TypeScript generados de Supabase. Helpers RLS para setear `app.current_tenant_id` en queries backend.
- **Estado:** README y migrations/. Sin tipos generados aún.

### `packages/ui`

- **Responsabilidad:** Componentes UI compartidos basados en shadcn/ui.
- **Estado:** Directorio vacío. Actualmente los componentes viven en `apps/web/components/`.

---

## 4. Infraestructura (`infra/`)

- `render.yaml` — [PENDIENTE] Configuración de deploy de todos los servicios en Render.
- Cada servicio tendrá su propio Web Service o Background Worker definido aquí.

---

## Regla de Actualización

**Este archivo DEBE actualizarse cada vez que:**
- Un módulo cambia de estado (❌ → 🟡 → ✅)
- Se agrega un nuevo módulo o ruta
- Se resuelve un BLOQUEANTE identificado