# Mapa de Navegación — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 3 — actualizado post Fases 8-11 completadas)

Este documento cubre **rutas y navegación únicamente**.

> **Alcance de este documento**: rutas reales, rutas faltantes y rutas propuestas.
> **No incluye**: dependencias de backend por módulo ni orden de implementación.
> Para eso ver:
> - `docs/product/admin-ui-modules.md` — Módulos con propósito y dependencia backend
> - `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend y orden de implementación

**Leyenda de estado**:
- ✅ **Existe en código** — archivo en `apps/web/app/**`
- 🟡 **Existe pero incompleto** — archivo existe, funcionalidad limitada
- ❌ **No existe** — no hay archivo de ruta en el repo

---

## A. TENANT CONSOLE

### Rutas reales en el repositorio hoy (Fases 1-11 completadas)

```
apps/web/app/
├── page.tsx                             ✅  /       → redirect a /dashboard o /login
├── layout.tsx                           ✅  Root layout (Inter font, globals.css)
├── login/
│   └── page.tsx                         ✅  /login  → Auth Supabase SSR + mensaje de error
└── dashboard/
    ├── layout.tsx                       ✅  /dashboard/* → Sidebar 13 ítems + RBAC visual + logout
    ├── page.tsx                         🟡  /dashboard  → Email + tenant name (sin KPIs)
    ├── inbox/
    │   └── page.tsx                     ✅  /dashboard/inbox → Realtime, human takeover, bubble UI
    ├── orders/
    │   └── page.tsx                     ✅  /dashboard/orders → Listado, detalle, estados
    ├── contacts/
    │   └── page.tsx                     ✅  /dashboard/contacts → Listado, perfil
    ├── catalog/
    │   └── page.tsx                     🟡  /dashboard/catalog → CRUD + edición + soft delete (variantes múltiples: pendiente)
    ├── inventory/
    │   └── page.tsx                     ✅  /dashboard/inventory → Stock, alertas, ajuste
    ├── knowledge-base/
    │   └── page.tsx                     ✅  /dashboard/knowledge-base → CRUD, categorías, toggle
    ├── media/
    │   ├── page.tsx                     ✅  /dashboard/media → Listado de archivos
    │   └── media-client.tsx             ✅  (Client Component — upload, delete, copy URL)
    ├── shipping/
    │   └── page.tsx                     🟡  /dashboard/shipping → Historial OK, cotización sin formulario UI
    ├── integrations/
    │   └── page.tsx                     ✅  /dashboard/integrations → MeLi + Envia connect/disconnect
    ├── metrics/
    │   └── page.tsx                     ✅  /dashboard/metrics → 4 KPIs, pedidos, top productos
    ├── audit/
    │   └── page.tsx                     ✅  /dashboard/audit → Filtros, paginación, payload expandible
    └── settings/
        └── page.tsx                     ✅  /dashboard/settings → Perfil, WABA, equipo, notificaciones
```

### Sidebar actual — verificado en `apps/web/app/dashboard/layout.tsx`

```tsx
// NAV_ITEMS con RBAC: roles: [] = visible para todos, ['owner','manager'] = restringido

{ href: '/dashboard',                label: 'Resumen',        roles: [] }              ✅
{ href: '/dashboard/inbox',          label: 'Inbox AI',       roles: [] }              ✅
{ href: '/dashboard/orders',         label: 'Pedidos',        roles: [] }              ✅
{ href: '/dashboard/contacts',       label: 'Contactos',      roles: [] }              ✅
{ href: '/dashboard/catalog',        label: 'Catálogo',       roles: ['owner','manager'] }  🟡
{ href: '/dashboard/inventory',      label: 'Inventario',     roles: ['owner','manager'] }  ✅
{ href: '/dashboard/knowledge-base', label: 'Knowledge Base', roles: ['owner','manager'] }  ✅
{ href: '/dashboard/media',          label: 'Media',          roles: ['owner','manager'] }  ✅
{ href: '/dashboard/shipping',       label: 'Envíos',         roles: [] }              🟡
{ href: '/dashboard/integrations',   label: 'Integraciones',  roles: ['owner'] }       ✅
{ href: '/dashboard/metrics',        label: 'Métricas',       roles: ['owner','manager'] }  ✅
{ href: '/dashboard/audit',          label: 'Auditoría',      roles: ['owner'] }       ✅
{ href: '/dashboard/settings',       label: 'Configuración',  roles: ['owner'] }       ✅
```

**Total**: 13 ítems. Todos tienen página correspondiente. Sin links rotos.

### Rutas faltantes (deuda técnica menor)

Ninguna ruta del sidebar está huérfana. Las funcionalidades faltantes son submódulos dentro de páginas existentes (no rutas nuevas), excepto:

| Ruta | Módulo | Justificación |
|------|--------|---------------|
| `/dashboard/shipping/quote` | Formulario cotización | Deuda UI — backend `POST /api/v1/shipping/quote` existe |
| `/dashboard/orders/new` | Crear pedido manual | Actualmente pedidos entran via API/MeLi |

---

## B. PLATFORM CONSOLE

> **Estado global: ❌ No implementada.**
> No existe ningún archivo de código, ruta ni layout de Platform Console en el repositorio.
> Prerequisito: OQ-P01 (misma app vs separada) debe decidirse primero.

### Rutas objetivo (Fase 12 — sin implementar)

```
/platform                                ❌  Overview Global
/platform/tenants                        ❌  Tenants (lista)
/platform/tenants/[id]                   ❌  Tenant Detail
/platform/health                         ❌  Health Center
/platform/integrations                   ❌  Integraciones Globales
/platform/jobs                           ❌  Jobs / Queue Ops
/platform/security                       ❌  Seguridad
/platform/audit                          ❌  Auditoría Global
/platform/billing                        ❌  Billing / Planes
/platform/flags                          ❌  Feature Flags
/platform/support                        ❌  Soporte Operativo
```

> Ninguno de estos módulos tiene código. Prerrequisito absoluto: `platform_users` tabla + auth diferenciada en `middleware.ts`.
> Ver `docs/product/personas-and-consoles.md` y `docs/architecture/front-back-separation.md` sección B.

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Módulos con estado, propósito y dependencia backend
- `docs/product/current-scope.md` — Stack real, endpoints, tablas, bloqueos
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend por módulo
