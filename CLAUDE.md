# CLAUDE.md — Commerce Ops Platform
> Guía de contexto para Claude Code. Leer antes de tocar cualquier archivo.

## Qué es este proyecto

SaaS conversacional multi-tenant para e-commerce B2B2C vía WhatsApp.
Cada empresa (tenant) opera en aislamiento total. El canal de ventas es WhatsApp Cloud API (Meta oficial). La IA es Google Gemini. El backend son microservicios Python/FastAPI. El frontend es Next.js 14.

**Estado actual:** Fases 1-11 ✅ completadas. Phase 12 (Platform Console) ❌ pendiente.
**Versión live:** https://commerce-ops-web.onrender.com

---

## Stack exacto (no asumir — verificar en package.json / requirements.txt)

| Capa | Tecnología |
|------|-----------|
| Frontend | Next.js 14.2.35 + React 18 + TypeScript 5 |
| UI | TailwindCSS 3.3 + shadcn/ui (componentes en `apps/web/components/ui/`) |
| Backend | Python 3.11 + FastAPI 0.128.8 (sin venv — paquetes en sistema) |
| DB/Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) |
| Storage | Supabase Storage — bucket `tenant-media` |
| IA | Google Gemini (`google-genai==1.47.0`, modelo `gemini-2.5-flash`) |
| WhatsApp | WhatsApp Cloud API v21.0 (Meta oficial — NUNCA librerías no oficiales) |
| Shipping | Envia API (sandbox + producción vía `tenant_integrations`) |
| Marketplace | Mercado Libre OAuth 2.0 |
| Hosting | Render (4 servicios: web, connector, api, orchestrator) |

---

## Arquitectura de navegación — Tenant Console (aprobada 2026-04-10)

```
Dashboard          /dashboard            (raíz — tabs internas: Operaciones/Negocio)
Inbox              /dashboard/inbox      (raíz — uso diario crítico)

▼ Ventas
   Pedidos          /dashboard/orders
   Contactos        /dashboard/contacts
   Envíos           /dashboard/shipping

▼ Productos        (owner + manager)
   Catálogo         /dashboard/catalog
   Inventario       /dashboard/inventory

▼ IA & Contenido   (owner + manager)
   Base de Conocimiento  /dashboard/knowledge-base
   Media                 /dashboard/media

▼ Analítica        (owner + manager)
   Métricas         /dashboard/metrics
   Auditoría        /dashboard/audit     (owner only)

▼ Configuración    (owner + manager)
   General          /dashboard/settings
   Integraciones    /dashboard/integrations  (owner only)
```

**Reglas de navegación:**
- Sub-item en sidebar = módulo con URL propia y propósito diferenciado
- Tabs dentro de una página = vistas alternativas del mismo dato (NO ir al sidebar)
- Los grupos auto-expanden cuando la ruta activa está dentro de ellos
- RBAC aplicado tanto en grupo como en cada hijo individual

---

## Estructura de directorios clave

```
apps/web/
  app/
    dashboard/
      sidebar-client.tsx       ← Navegación (grupos expandibles)
      layout.tsx               ← Layout principal con SidebarClient
      dashboard-client.tsx     ← Dashboard con tabs Operaciones/Negocio
      inbox/page.tsx           ← Inbox AI realtime
      orders/page.tsx          ← Pedidos con filtros
      contacts/page.tsx        ← Contactos CRM
      catalog/page.tsx         ← Catálogo con CatalogForm client
      inventory/page.tsx       ← Inventario con ajustes
      knowledge-base/page.tsx  ← KB con búsqueda
      media/
        page.tsx               ← Server: lista archivos Storage
        media-client.tsx       ← Client: drag&drop, lightbox
      shipping/page.tsx        ← Envíos (bajo Ventas en nav)
      metrics/page.tsx         ← Métricas históricas
      audit/page.tsx           ← Auditoría con filtros
      settings/page.tsx        ← Configuración General
      integrations/page.tsx    ← Integraciones (bajo Config en nav)
  components/ui/               ← shadcn/ui components
  utils/supabase/
    client.ts                  ← Supabase browser client
    server.ts                  ← Supabase server client (cookies)

services/
  api/                         ← FastAPI: gateway, RBAC, productos, pedidos
  connector-whatsapp/          ← Webhook Meta → Supabase messages
  ai-orchestrator/             ← Gemini + KB + intención → respuesta
```

---

## Reglas críticas para Claude Code

### Seguridad
1. **getUser() NO getSession()** en Server Components — `getSession()` no valida JWT contra servidor
2. **RLS activo en Supabase** — toda query del frontend debe incluir `tenant_id` (el RLS lo filtra automáticamente por el JWT)
3. **Server Actions deben re-validar tenant_id y role** — nunca confíar en el cliente

### Multi-tenant
4. Toda tabla tiene `tenant_id`. Toda query tiene `.eq('tenant_id', tenantId)`
5. `app_metadata.tenant_id` y `app_metadata.role` vienen del JWT de Supabase Auth
6. RLS es la última barrera. El API Gateway es la barrera previa. El frontend no es seguridad.

### Frontend patterns
7. **Server Components** para carga inicial de datos (`async function Page()`)
8. **Client Components** para interactividad (hooks, realtime, drag&drop)
9. Server Actions (`'use server'`) re-validan con `getUser()` internamente
10. `revalidatePath()` después de toda mutación exitosa

### IA
11. Gemini nunca es fuente de verdad para stock, precios, pedidos, permisos
12. La KB (Base de Conocimiento) se inyecta como texto plano en el prompt
13. RAG con pgvector está planificado — no implementado aún (OQ-T03)

### Shipping
14. Envia API solo disponible si `tenant_integrations.status = 'connected'` para provider `envia`
15. `shipping_origin` se guarda como JSONB en `tenants.shipping_origin`

### WhatsApp
16. Solo WhatsApp Cloud API oficial (Meta v21.0). NUNCA Baileys, WPPConnect ni similares
17. El connector recibe webhooks → inserta en `messages` → orchestrator procesa

---

## Comandos útiles

```bash
# Frontend dev
cd apps/web && npm run dev

# TypeScript check
cd apps/web && node_modules/.bin/tsc --noEmit

# Backend API
cd services/api && uvicorn main:app --reload

# Orchestrator local
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py

# DB query
supabase db query --linked -f archivo.sql
```

---

## Variables de entorno (.env — nunca al repo)

```
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
META_ACCESS_TOKEN=          # Token permanente System User commerce-ops
META_PHONE_NUMBER_ID=
META_WABA_ID=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
MELI_CLIENT_ID=
MELI_CLIENT_SECRET=
MELI_REDIRECT_URI=
NEXT_PUBLIC_API_URL=https://commerce-ops-api.onrender.com
```

---

## Estado de fases

| Fase | Nombre | Estado |
|------|--------|--------|
| 1-6 | Base, Auth, UI, WhatsApp, AI, API Gateway | ✅ |
| 7 | Deploy Render + E2E | ✅ |
| 8 | Catálogo + RBAC | ✅ |
| 9 | Schema core + Pedidos + Config + Equipo | ✅ |
| 10 | MeLi OAuth + Envia Sandbox | ✅ |
| 11 | Módulos restantes + UI Redesign "Plus Total" | ✅ |
| 12 | Platform Console | ❌ Bloqueado por OQ-P01 |
| 13 | Shopify / Tienda custom | ❌ Futuro |

---

## Preguntas abiertas (OQ)

- **OQ-P01**: ¿Platform Console en misma app Next.js (`/platform/*`) o app separada?
- **OQ-T03**: pgvector para RAG en KB — ¿Supabase managed o extensión manual?

Ver detalles en `docs/roadmap/implementation-phases.md`
