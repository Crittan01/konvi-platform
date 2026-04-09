# Módulos del Monorepo — Responsabilidades y Estado

## Estado Global — Actualizado 2026-04-08

```
apps/web              ✅ Funcional (Auth, Dashboard, Catálogo, Inbox AI)
services/
  connector-whatsapp  ✅ Fix aplicado (tenant resolver por meta_waba_id real)
  ai-orchestrator     ✅ Implementado (worker + orchestrator + guardrails + server)
  api                 ✅ Implementado (JWT real, CRUD productos + conversaciones)
  connector-meli      ❌ Pendiente (Fase 8)
  connector-shopify   ❌ Pendiente (futuro)
packages/auth         🟡 Parcial (lógica en apps/web/utils/supabase/)
packages/db           🟡 Parcial (sin tipos TypeScript generados aún)
packages/ui           ❌ Vacío (componentes en apps/web/components/)
```

> ⚠️ `services/orchestrator/` fue eliminado el 2026-04-08 — era un prototipo obsoleto sin requirements.txt,
> sin graceful shutdown, con bug de async/sync y usando Meta Graph API v18.0 (actual: v21.0).
> La implementación canónica es `services/ai-orchestrator/`.

**Supabase (proyecto `***SUPABASE_PROJECT_REF_REDACTED***`):**
- Tenant `Matriz Commerce Dev`: `status=active`, `meta_waba_id=2159052118202272` ✅
- 6 migraciones aplicadas, incluyendo `messages.processed` BOOLEAN + índice parcial ✅

**Sistema VM (entorno dev, sin venv):**
- `supabase` CLI v2.84.2 — `/usr/local/bin/supabase` ✅
- `psql` 15.17 — via DNF ✅ (TCP bloqueado por Supavisor — usar CLI `--linked`)

**Paquetes Python en requirements.txt (versiones de producción):**
```
google-genai==1.47.0       ← SDK NUEVO (no usar google-generativeai que está deprecado)
supabase==2.28.3
httpx==0.28.1
pydantic==2.12.5
PyJWT==2.10.1              ← solo en services/api
fastapi==0.115.12
uvicorn[standard]==0.34.0
python-dotenv==1.0.1
```

> ⚠️ La VM tiene instalado `supabase==2.10.0` vía pip3 de sistema (sin venv).
> Los requirements.txt especifican `supabase==2.28.3`. En Render se instala 2.28.3.
> Para alinear el entorno local, ejecutar: `pip3 install supabase==2.28.3`

**Credenciales activas:**
- `META_ACCESS_TOKEN`: token temporal ~24h (ver IH-003). **Renovar si expirado.**
- `meta_waba_id`: `2159052118202272` ✅
- `GEMINI_API_KEY`: ✅ configurada en `.env`
- `SUPABASE_JWT_SECRET`: ⚠️ Pendiente obtener (IH-005)

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
- **Estado**: ✅ Implementado (Fase 6). Endpoints activos:
  - `GET /health`
  - `GET /api/v1/products` — Catálogo del tenant (JWT + RLS)
  - `GET /api/v1/conversations` — Inbox paginado del tenant
- **Pendiente**: RBAC (owner/manager/agent) enforceado por endpoint.

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
