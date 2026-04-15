# Ecosistema de Servicios — Snapshot Empírico

El sistema se compone de 4 servicios independientes ejecutándose en Render, comunicados asíncronamente vía Supabase PostgreSQL.

## 1. apps/web (Frontend)
- **Tecnología**: Next.js 14.2.35 (App Router).
- **Función comprobada**: Dashboard de control, Inbox en tiempo real, Gestión de catálogo y pedidos.
- **Acceso DB**: Directo vía Supabase SDK (Client/Server).
- **Acceso API**: Vía `fetch` con JWT de sesión.

## 2. services/connector-whatsapp (Boundary)
- **Tecnología**: FastAPI.
- **Función comprobada**: Receptor de Webhooks de Meta.
- **Seguridad**: Validación de firma `X-Hub-Signature-256` (HMAC-SHA256).
- **Aislamiento**: Resolución dinámica de `tenant_id` por `meta_waba_id`.
- **Integridad**: Persistencia asíncrona (`BackgroundTasks`) en Supabase.
- **URL**: `https://commerce-ops-connector.onrender.com`

## 3. services/ai-orchestrator (Worker)
- **Tecnología**: Python Polling Worker.
- **Función comprobada**: Procesamiento de mensajes (`direction=inbound, processed=False`).
- **Lógica IA**: Gemini-2.5-flash (JSON Mode) con RAG simple (Catálogo + KB).
- **Acceso DB**: `service_role` con inyección manual de `tenant_id` en contexto de base de datos.
- **Salida**: Envío directo a Meta Graph API v21.0. No depende de otros servicios internos para emitir.

## 4. services/api (Gateway)
- **Tecnología**: FastAPI.
- **Función comprobada**: Orquestación de lógica de negocio compleja.
- **Seguridad**: Validación de JWT `tenant_id` + RBAC base (`owner`, `manager`, `agent`).
- **URL**: `https://commerce-ops-api.onrender.com`

---

## Flujo de Mensaje WhatsApp (End-to-End Verificado)

1. **Meta Webhook** → `connector-whatsapp`
2. `connector-whatsapp` → **INSERT messages** (`direction=inbound, processed=false`)
3. **Supabase Realtime** → Notifica a `apps/web/inbox` (UI se actualiza al instante).
4. `ai-orchestrator` (Polling) → Detecta mensaje nuevo.
5. **Gemini** → Genera respuesta con contexto del tenant.
6. `ai-orchestrator` → **POST Meta Graph API** (Mensaje saliente).
7. `ai-orchestrator` → **INSERT messages** (`direction=outbound`) + **UPDATE processed=true**.
8. **Supabase Realtime** → Notifica a `apps/web/inbox` (Respuesta del bot aparece en la UI).

---

## Monitoreo y Salud (Free Tier Compliance)
Cada servicio backend implementa un endpoint `/health`:
- `connector-whatsapp`: HTTP
- `api`: HTTP
- `ai-orchestrator`: Thread separado (`server.py`) para evitar el "Background Worker" prohibido en el plan Free de Render.
