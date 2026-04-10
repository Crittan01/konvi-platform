# Módulos del Monorepo — Responsabilidades y Estado

## Estado Global

> Estado actual por módulo → `docs/product/current-scope.md`
> Stack con versiones → `.context/02-stack.md`

**Resumen**: Fases 1-11 ✅. `apps/web` (13/13 módulos), `services/api` (8 routers), `connector-whatsapp`, `ai-orchestrator` todos live en Render. Supabase: 13 migraciones aplicadas.

---

## 1. Aplicaciones (`apps/*`)

### `apps/web`

- **Responsabilidad:** Panel Backoffice para operadores de e-commerce. Permite gestionar catálogo, ver conversaciones y auditar respuestas de la IA.
- **Pila Técnica:** Next.js **14.2.35** (App Router), React ^18, TailwindCSS ^3.3.0, shadcn/ui (5 componentes), TypeScript ^5. Dark Warm Theme.
- **Auth SSR:** `@supabase/ssr` via `middleware.ts` — protege todas las rutas `/dashboard`. `getUser()` en todos los Server Components (seguro JWT).
- **13/13 módulos Tenant Console activos**: `/dashboard`, `/dashboard/inbox`, `/dashboard/catalog`, `/dashboard/orders`, `/dashboard/contacts`, `/dashboard/inventory`, `/dashboard/knowledge-base`, `/dashboard/media`, `/dashboard/shipping`, `/dashboard/integrations`, `/dashboard/metrics`, `/dashboard/audit`, `/dashboard/settings`
- **Platform Console**: ❌ No existe — Fase 12 (bloqueante: OQ-P01)
- **Relaciones:** Consume Supabase directamente en Server Components + Server Actions. Consume `services/api` para operaciones transaccionales (órdenes, shipping, integraciones, settings, equipo).

---

## 2. Servicios Backend (`services/*`)

### `services/connector-whatsapp`

- **Responsabilidad:** Boundary gateway para Meta. Recibe webhooks de WhatsApp, valida firma HMAC-SHA256, y delega el procesamiento a un Background Task.
- **Pila:** FastAPI, `supabase-py 2.28.3`, `httpx 0.28.1`.
- **Patrón:** Fire-and-forget — retorna HTTP 200 en milisegundos (política Meta).
- **Estado**: ✅ Fix aplicado 2026-04-07 — tenant resolver por `meta_waba_id` real.

### `services/ai-orchestrator` ← **Módulo core del ciclo IA**

- **Responsabilidad:** Worker asíncrono. Lee mensajes no procesados, construye contexto del tenant, llama a Gemini, valida el output, y envía la respuesta por WhatsApp Cloud API.
- **Pila:** Python 3.9+, `google-genai==1.47.0` (nuevo SDK oficial), `pydantic==2.12.5`, `supabase-py 2.28.3`.
- **Patrón Render:** Web Service (Free plan) — `server.py` expone FastAPI con `/health` + `/status`, y lanza el worker en un daemon thread.
- **Flujo:**
  ```
  Loop(polling cada 3s)
    → SELECT messages WHERE processed=False AND direction='inbound' LIMIT 10
    → Obtener catálogo del tenant (context injection)
    → Construir historial de conversación (últimos 10 msgs)
    → Llamar Gemini (JSON mode) → OrchestratorOutput Pydantic
    → Guardrails: confidence ≥ 0.65, no texto vacío, longitud ≤ 1000 chars, escalación humana
    → Enviar respuesta vía Meta Graph API v21.0
    → INSERT message(outbound) + UPDATE processed=True + processed_at
  ```
- **Estado**: ✅ Implementado 2026-04-07. Archivos:
  - `server.py` — Entry point Render (uvicorn server:app + worker en thread)
  - `main.py` — Entry point local (asyncio.run + SIGTERM handler)
  - `worker.py` — Loop polling configurable (`POLL_INTERVAL_SECONDS`, default 3s)
  - `orchestrator.py` — Context builder + Gemini JSON mode + `OrchestratorOutput` Pydantic
  - `guardrails.py` — 4 reglas de validación
  - `whatsapp_sender.py` — POST Meta Graph API v21.0 via httpx async
  - `tools/catalog_tool.py` — Lee productos activos del tenant (async)
- **Pendiente para producción**: Deploy en Render (Fase 7) + META_ACCESS_TOKEN permanente (IH-006)

### `services/api`

- **Responsabilidad:** REST API sincrónica para el Frontend. CRUD de catálogos, conversaciones, con JWT Supabase validado.
- **Pila:** FastAPI, `supabase-py 2.28.3`, `PyJWT 2.10.1`.
- **Estado**: ✅ Live en Render. 8 routers activos: products, orders, contacts, settings, integrations, shipping, meli_webhook, conversations
- **RBAC**: Base enforceado — owner/manager/agent con decorador por endpoint. R-09 parcialmente resuelto.

### `services/connector-mercadolibre` (Fase 8)

- **Responsabilidad:** Sincronización de catálogo y pedidos con MercadoLibre API.
- **Estado:** Directorio vacío. Pendiente.

### `services/connector-shopify` (Futuro)

- **Responsabilidad:** Integración con Shopify Storefront y Admin API.
- **Estado:** Directorio vacío. Pendiente.

---

## 3. Paquetes Compartidos (`packages/*`)

### `packages/auth`

- **Responsabilidad:** Wrappers SSR oficiales de Supabase Auth para Next.js. Custom claims JWT con `tenant_id`.
- **Estado:** README y package.json. Lógica actualmente en `apps/web/utils/supabase/`.

### `packages/db`

- **Responsabilidad:** Tipos TypeScript generados de Supabase. Helpers RLS para setear `app.current_tenant_id` en queries backend.
- **Estado:** README y migrations/. Sin tipos generados aún. Pendiente: `supabase gen types typescript`.

### `packages/ui`

- **Responsabilidad:** Componentes UI compartidos basados en shadcn/ui.
- **Estado:** Directorio vacío. Componentes actualmente en `apps/web/components/`.

---

## 4. Scripts de Soporte (`scripts/*`)

### `scripts/test_worker_e2e.py`

- **Responsabilidad:** Test E2E del ciclo completo del AI Orchestrator.
- **Apunta a:** `services/ai-orchestrator` (canónico).
- **Uso:** `python3 scripts/test_worker_e2e.py` con `.env` configurado.
- **Mock:** El envío a Meta API está mockeado — no requiere token activo.

---

## Regla de Actualización

**Este archivo DEBE actualizarse cada vez que:**
- Un módulo cambia de estado (❌ → 🟡 → ✅)
- Se agrega un nuevo módulo o ruta
- Se resuelve un BLOQUEANTE identificado
- Cambia una versión de dependencia relevante
