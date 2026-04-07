# Módulos del Monorepo — Responsabilidades y Estado


## Estado Global — Actualizado 2026-04-07T21:30 CDT

```
apps/web              ✅ Funcional (Auth, Dashboard, Catálogo, Inbox AI)
services/
  connector-whatsapp  ✅ Fix aplicado (tenant resolver por meta_waba_id real)
  ai-orchestrator     ✅ Implementado (worker + orchestrator + guardrails + sender)
  api                 🟡 Esqueleto con mocks (Fase D pendiente)
  connector-meli      ❌ Pendiente (Fase 4)
  connector-shopify   ❌ Pendiente (futuro)
packages/auth         🟡 Parcial
packages/db           🟡 Parcial
```

**Supabase (proyecto `xmelwnhhphksbpdjmbbp`):**
- Tenant `Matriz Commerce Dev`: `status=active`, `meta_waba_id=2159052118202272` ✅
- Migración `messages.processed` (BOOLEAN + índice parcial): ✅ Aplicada

**Sistema VM (entorno dev, sin venv):**
- `supabase` CLI v2.84.2 — `/usr/local/bin/supabase` ✅
- `psql` 15.17 — via DNF ✅
- Python packages (pip3 sistema): `supabase==2.28.3`, `google-generativeai==0.8.6`, `httpx==0.28.1`, `pydantic==2.12.5` ✅

**Credenciales activas:**
- `META_ACCESS_TOKEN`: renovado 2026-04-07 (token temporal ~24h, ver [IH-003])
- `meta_waba_id`: `2159052118202272` ✅


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
  - `/dashboard/inbox` — ✅ Bandeja de conversaciones con Realtime, Human Takeover, hilo visual
- **Relaciones:** Consume Supabase directamente en Server Components. En el futuro, consumirá `services/api` para operaciones transaccionales complejas.

---

## 2. Servicios Backend (`services/*`)

### `services/connector-whatsapp`

- **Responsabilidad:** Boundary gateway para Meta. Recibe webhooks de WhatsApp, valida firma HMAC-SHA256, y delega el procesamiento a un Background Task.
- **Pila:** FastAPI (Python 3.11+), `python-supabase`.
- **Patrón:** Fire-and-forget — retorna HTTP 200 en milisegundos (política Meta).
- **Estado**: ✅ Fix aplicado 2026-04-07 — tenant resolver por `meta_waba_id` real.
- ~~**BLOQUEANTE #1:**~~ `db_persistence.py` — RESUELTO: filtra por `meta_waba_id` + `status=active`, singleton lazy de cliente, manejo de errores robusto.

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
- **Estado**: ✅ Implementado 2026-04-07. Archivos:
  - `main.py` — Entry point con graceful shutdown (SIGTERM para Render)
  - `worker.py` — Loop polling configurable (`POLL_INTERVAL_SECONDS`, default 3s), batch de 10 msgs
  - `orchestrator.py` — Context builder (catálogo + historial) + Gemini JSON mode + `OrchestratorOutput` Pydantic
  - `guardrails.py` — 4 reglas: confidence mínima (0.65), texto vacío, longitud máx (1000 chars), escalación humana
  - `whatsapp_sender.py` — POST Meta Graph API v21.0 con httpx async
  - `tools/catalog_tool.py` — Lee productos activos del tenant para inyectar en el prompt
- **Pendiente para activar**: `GEMINI_API_KEY` en `.env` + deploy en Render

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