# Current Scope — Estado Real de Implementación

Última actualización: 2026-04-10 (rev. 16 — UI Plus Total 13 módulos + nav reestructurada con grupos expandibles)

Este documento registra el estado **real y verificado en el repositorio** del producto hoy.
Distingue explícitamente entre lo implementado, lo parcial y lo pendiente.

> **Fuente de verdad**: código en el repo, no documentación previa ni intenciones.

---

## Stack real vigente (verificado en repo)

### Frontend — `apps/web`

| Elemento | Versión real en repo | Notas |
|----------|---------------------|-------|
| Next.js | **14.2.35** | `apps/web/package.json` — actualizado desde 14.1.0 (CVE patch) |
| React | ^18 | — |
| TypeScript | ^5 | — |
| TailwindCSS | ^3.3.0 | Con `postcss.config.js` (fix Render) |
| shadcn/ui components | 5 componentes | En `apps/web/components/ui/` — badge, button, card, input, label |
| `@supabase/ssr` | ^0.10.0 | — |
| `@supabase/supabase-js` | ^2.101.1 | — |
| Patrón routing | App Router | Confirmado por estructura `app/` |
| Server Actions | Sí | Usado en catalog, knowledge-base, inventory |
| Font | Inter via `next/font/google` | CSS variable `--font-inter`, integrada en `tailwind.config.ts` |

> **`packages/ui`**: directorio vacío — sin archivos. Los componentes viven en `apps/web/components/ui/`.

### Backend — servicios Python

| Elemento | Versión real | Notas |
|----------|-------------|-------|
| Python (VM) | **3.11.13** | Sin venv — paquetes en sistema. `Optional[X]` es el estilo usado. |
| FastAPI | 0.128.8 | Todos los servicios |
| Pydantic | 2.12.5 | — |
| google-genai | 1.47.0 | SDK oficial Gemini — no `google-generativeai` |
| supabase-py | 2.28.3 | — |
| PyJWT | 2.10.1 | Solo en `services/api` |

> **Python objetivo**: 3.11+ para producción. La VM usa 3.9.25 (EOL). No actualizar sin revisar impacto en Oracle Linux 9.

### Packages — estado real

| Package | Archivos | Estado |
|---------|----------|--------|
| `packages/auth` | `lib/server-client.ts`, `lib/client-browser.ts` | 🟡 Parcial — 2 archivos implementados |
| `packages/db` | `migrations/` (5 archivos SQL — mirrors iniciales) | 🟡 Parcial — las 13 migraciones reales están en `supabase/migrations/` |
| `packages/ui` | — | ❌ Vacío — componentes en `apps/web/components/ui/` |
| `packages/config` | — | ❌ Vacío |
| `packages/shared-types` | — | ❌ Vacío |

---

## Resumen ejecutivo de implementación

| Capa | Estado | Notas |
|------|--------|-------|
| Tenant Console | ✅ Completa (13/13 módulos) | UI "Plus Total" — Enterprise SaaS responsive — commit 6a496c7 |
| Navegación Tenant | ✅ Reestructurada | Grupos expandibles, RBAC dual, auto-expand activo — commit pendiente |
| Platform Console | ❌ No existe | Cero rutas, cero layout, cero auth de plataforma |
| Backend services | ✅ 3 servicios live + 11 routers | WhatsApp connector, API Gateway, AI Orchestrator |
| Base de datos | ✅ 13 migraciones aplicadas | Incluyendo schema core, shipments, stock_movements, kb_documents, audit_log, low_stock_threshold, consent |
| Deploy Render | ✅ Completo | 4 servicios live, E2E confirmado |
| Shipping/Courier (Envia) | 🟡 Fase Inicial | Quote + historial operativos. Sandbox conectado. Label/tracking: Fase 2 |
| MeLi | 🟡 Fase Inicial | OAuth conectado user_id `603780765`. Sync catálogo/stock: futuro |

---

## Frontend — rutas reales en repo (Fases 1-11 completas)

```
apps/web/app/
├── page.tsx                             ✅ Landing / redirect a /dashboard o /login
├── layout.tsx                           ✅ Root layout (Inter font, globals.css)
├── globals.css                          ✅ Dark Warm Theme: carbón cálido + verde bosque + ámbar
├── login/
│   └── page.tsx                         ✅ Auth con Supabase SSR + mensaje de error
└── dashboard/
    ├── layout.tsx                       ✅ Sidebar 13 ítems + RBAC visual + logout
    ├── page.tsx                         ✅ Dashboard — Tabs Operaciones/Negocio, KPIs, recharts
    ├── inbox/
    │   └── page.tsx                     ✅ Inbox AI — Realtime, human takeover, bubble UI
    ├── catalog/
    │   └── page.tsx                     ✅ Catálogo — CRUD completo, multi-variante, mobile-first UX, archivados y auto-refresh
    ├── orders/
    │   └── page.tsx                     ✅ Pedidos — listado, detalle, cambio de estado
    ├── contacts/
    │   └── page.tsx                     ✅ Contactos — listado, perfil
    ├── inventory/
    │   └── page.tsx                     ✅ Inventario — stock por variante, alertas, ajuste, paginación, búsqueda en memoria
    ├── knowledge-base/
    │   └── page.tsx                     ✅ Knowledge Base — CRUD, categorías, toggle activo
    ├── media/
    │   ├── page.tsx                     ✅ Media — Server Component lista archivos
    │   └── media-client.tsx             ✅ Upload, delete, copy URL (Client Component)
    ├── shipping/
    │   └── page.tsx                     ✅ Shipping — historial + ShippingQuoteForm interactivo con selección de carrier
    ├── integrations/
    │   └── page.tsx                     ✅ Integraciones — estado MeLi + Envia, connect/disconnect
    ├── metrics/
    │   └── page.tsx                     ✅ Métricas — 4 KPIs, pedidos por estado, top 5 productos
    ├── audit/
    │   └── page.tsx                     ✅ Auditoría — filtros, paginación 25/pág, payload expandible
    └── settings/
        └── page.tsx                     ✅ Configuración — perfil, WABA, equipo, notificaciones
```

**Sidebar actual** (verificado en `apps/web/app/dashboard/sidebar-client.tsx`):
Usa árbol de grupos expandibles con auto-expand y RBAC dual.
- Raíz: Dashboard, Inbox
- Ventas: Pedidos, Contactos, Envíos, Reclamos (Pronto)
- Productos: Catálogo, Inventario
- Publicaciones (Pronto): Mercado Libre, Central Ofertas
- Compras (Pronto): Órdenes de Compra
- Finanzas (Pronto): Ingresos & Gastos, Rentabilidad
- IA & Contenido: Base de Conocimiento, Media, Agentes IA (Pronto)
- Analítica: Métricas, Auditoría
- Configuración: General, Integraciones

---

## Estado detallado por módulo — Tenant Console

| Módulo | Ruta | Estado | Notas |
|--------|------|--------|-------|
| Dashboard | `/dashboard` | ✅ Implementado | Tabs Operaciones + Negocio. KPIs, gráficas recharts. |
| Inbox | `/dashboard/inbox` | ✅ Implementado | Realtime, takeover, hilo |
| Catálogo | `/dashboard/catalog` | 🟡 Parcial | CRUD + edit + delete. Variantes múltiples: pendiente |
| Pedidos | `/dashboard/orders` | ✅ Implementado | Listado, detalle, estados. + AI Insight Panel |
| Contactos | `/dashboard/contacts` | ✅ Implementado | Listado, perfil. + AI Insight Panel |
| Inventario | `/dashboard/inventory` | ✅ Implementado | Paginación, búsqueda, responsive UX, ajuste stock con protección de doble clic |
| Knowledge Base | `/dashboard/knowledge-base` | ✅ Implementado | CRUD, categorías, activo/inactivo |
| Media | `/dashboard/media` | ✅ Implementado | Upload/delete/URL, bucket `tenant-media` |
| Shipping | `/dashboard/shipping` | ✅ Implementado | Historial + ShippingQuoteForm interactivo con tabla de carriers |
| Integraciones | `/dashboard/integrations` | ✅ Implementado | MeLi + Envia connect/disconnect |
| Métricas | `/dashboard/metrics` | ✅ Implementado | 4 KPIs, queries paralelas. + AI Insight Panel |
| Auditoría | `/dashboard/audit` | ✅ Implementado | Filtros, paginación, payload JSONB |
| Configuración | `/dashboard/settings` | ✅ Implementado | Equipo RBAC, WABA, notificaciones |
| Reclamos | `/dashboard/claims` | 🔒 Pronto | Stub page (visión de producto, Fase 12) |
| MeLi Listings | `/dashboard/marketplace` | 🔒 Pronto | Stub page (visión de producto, Fase 13) |
| Compras | `/dashboard/purchases` | 🔒 Pronto | Stub page (visión de producto, Fase 12.2) |
| Finanzas | `/dashboard/finance` | 🔒 Pronto | Stub page (visión de producto, Fase 12.3) |
| Agentes IA | `/dashboard/ai-agents` | 🔒 Pronto | Stub page (gestión prompts/skills, Fase 14) |
| API AI Insights | `/api/insights` | ✅ Implementado | Router genérico a Gemini con RBAC y prompts por dominio |

---

## Platform Console

**Estado**: ❌ No existe en absoluto.

- No hay rutas `/platform/*`
- No hay layout de platform console
- No hay tabla `platform_users` en DB
- No hay separación de auth para operadores de plataforma
- **Prerrequisito bloqueante**: OQ-P01 (misma app vs separada) debe resolverse antes de empezar

---

## Backend services — estado real

| Servicio | Estado | URL / Evidencia |
|----------|--------|-----------------|
| `services/connector-whatsapp` | ✅ Live en Render | `https://commerce-ops-connector.onrender.com` |
| `services/ai-orchestrator` | ✅ Live en Render | Background worker, polling cada 3s |
| `services/api` | ✅ Live en Render | `https://commerce-ops-api.onrender.com` |

### Routers activos en `services/api`

| Router | Endpoints clave | Estado |
|--------|----------------|--------|
| `products.py` | `GET/POST /api/v1/products`, `PUT/DELETE /products/{id}` | ✅ |
| `orders.py` | `GET/POST /api/v1/orders`, `PATCH /orders/{id}` | ✅ |
| `contacts.py` | `GET/POST /api/v1/contacts` | ✅ |
| `settings.py` | `GET/PUT /api/v1/settings`, `GET/POST/DELETE /team` | ✅ |
| `integrations.py` | `/integrations/envia`, `/integrations/meli`, OAuth callback | ✅ |
| `shipping.py` | `POST /api/v1/shipping/quote`, `GET /shipping/history` | ✅ |
| `meli_webhook.py` | `POST /api/v1/meli/webhook` | ✅ |
| `conversations.py` | `GET /api/v1/conversations` | ✅ |

### Endpoints significativos pendientes (próximas fases)

| Endpoint | Fase | Justificación |
|----------|------|---------------|
| `POST /api/v1/shipping/label` | Envia Fase 2 | Generación de etiqueta |
| `GET /api/v1/shipping/tracking/{id}` | Envia Fase 2 | Tracking real |
| `POST /api/v1/shipping/pickup` | Envia Fase 2 | Programar recolección |
| Endpoints platform-only | Fase 12 | Platform Console |

---

## Tablas de base de datos — estado real (13 migraciones aplicadas)

| Tabla | Migración | Estado |
|-------|-----------|--------|
| `tenants` | 20260406181235 | ✅ |
| `tenant_users` | 20260406181235 | ✅ |
| `products` | 20260406181236 | ✅ |
| `product_variations` | 20260406181236 | ✅ |
| `conversations` | 20260406181237 | ✅ |
| `messages` | 20260406181237 + processed flag | ✅ |
| `contacts` | 20260409220000 (Fase 9) | ✅ |
| `orders` | 20260409220000 (Fase 9) | ✅ |
| `order_items` | 20260409220000 (Fase 9) | ✅ |
| `tenant_integrations` | 20260409220000 (Fase 9) | ✅ |
| `notification_settings` | 20260409220000 (Fase 9) | ✅ |
| `shipments` | 20260409230000 (Fase 9) | ✅ |
| `stock_movements` | 20260409240000 (Fase 11) | ✅ |
| `kb_documents` | 20260409250000 (Fase 11) | ✅ |
| `audit_log` | 20260409260000 (Fase 11) | ✅ |
| `platform_users` | — | ❌ Fase 12 |

---

## Bloqueos activos

| Bloqueante | Tipo | Impacto |
|-----------|------|---------|
| OQ-P01 sin decidir (arquitectura Platform Console) | Decisión pendiente | Bloquea inicio de Fase 12 |
| ~~Python 3.9.25 en VM (EOL)~~ | ✅ Resuelto — Python 3.11.13 instalado 2026-04-10 | — |

## Deuda técnica resuelta (2026-04-10)

| Ítem | Resolución |
|------|-----------|
| RBAC granular en settings.py (R-09) | ✅ Añadido `require_owner_role` a `auth.py`. `settings.py` refactorizado: 3 endpoints usan `require_owner_role`, 1 usa `require_write_role`. Eliminados checks manuales. |
| `packages/db/migrations/` desincronizado | ✅ 14 migraciones canónicas sincronizadas. README actualizado indicando `supabase/migrations/` como fuente canónica. |
| Variantes múltiples — solo editable en UI para productos 1-variante | ✅ API: 3 nuevos endpoints (`PATCH /variations/{id}`, `POST /variations`, `DELETE /variations/{id}`). UI: edición por variante individual en todos los productos. Server Actions migradas a `getUser()`. |

## Procedimiento para Python 3.11 (requiere acción humana en VM)

```bash
# En la VM:
sudo dnf install python3.11 python3.11-pip -y
python3.11 -m pip install google-genai==1.47.0 supabase==2.28.3 httpx==0.28.1 \
  pydantic==2.12.5 PyJWT==2.10.1 fastapi==0.128.8 uvicorn==0.39.0 \
  python-dotenv==1.2.1 python-multipart==0.0.20 anyio==4.12.1 starlette==0.49.3

# Validar localmente:
python3.11 -m uvicorn main:app --port 8001

# En Render Dashboard → cada servicio → Start Command: cambiar python3 → python3.11
```

---

## Stack objetivo (no vigente todavía)

| Elemento | Real hoy | Objetivo |
|----------|----------|----------|
| Next.js | 14.2.35 | 15.x (cuando sea estable para el proyecto) |
| Python | 3.9.25 (EOL) | 3.11+ (antes de Beta) |
| packages/ui | Vacío | Componentes shadcn/ui compartidos entre apps |
| packages/shared-types | Vacío | Tipos TypeScript generados de Supabase |

> No actualizar versiones automáticamente. Cada upgrade requiere validar impacto en Render y en código existente.

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Módulos con evidencia, dependencias y prioridad
- `docs/product/navigation-map.md` — Rutas reales y sidebar actual
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend con BLOQUEs de implementación
- `docs/roadmap/implementation-phases.md` — Fases 1-13 con estado
