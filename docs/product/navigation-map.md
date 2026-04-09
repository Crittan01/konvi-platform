# Mapa de Navegación — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 2 — nota de alcance añadida)

Este documento cubre **rutas y navegación únicamente**.

> **Alcance de este documento**: rutas reales, rutas faltantes y rutas propuestas.
> **No incluye**: dependencias de backend por módulo ni orden de implementación.
> Para eso ver:
> - `docs/product/admin-ui-modules.md` — Módulos con propósito y dependencia backend
> - `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend y **orden de implementación** (BLOQUES 1-6)

**Leyenda de estado**:
- ✅ **Existe en código** — archivo en `apps/web/app/**`
- 🟡 **Existe pero incompleto** — archivo existe, funcionalidad limitada
- ❌ **No existe** — no hay archivo de ruta en el repo
- 📋 **Propuesta** — diseñada pero no existe ni está en el sidebar

---

## A. TENANT CONSOLE

### Rutas reales en el repositorio hoy

```
apps/web/app/
├── page.tsx                     ✅  /       → redirect a /dashboard o /login
├── layout.tsx                   ✅  Root layout (fuentes, globals.css)
├── login/
│   └── page.tsx                 ✅  /login  → Auth con Supabase SSR
└── dashboard/
    ├── layout.tsx               ✅  /dashboard/* → Sidebar con 3 ítems
    ├── page.tsx                 🟡  /dashboard  → Muestra email + tenant name
    ├── catalog/
    │   └── page.tsx             🟡  /dashboard/catalog → CRUD básico (solo primera variante)
    └── inbox/
        └── page.tsx             ✅  /dashboard/inbox → Realtime, human takeover
```

**Sidebar actual** (verificado en `apps/web/app/dashboard/layout.tsx`):
```tsx
<Link href="/dashboard">   Resumen     </Link>   // ✅ existe página
<Link href="/dashboard/catalog">  Catálogo  </Link>  // 🟡 existe, parcial
<Link href="/dashboard/inbox">  Inbox AI  </Link>   // ✅ existe, funcional
```

No hay links rotos: los 3 ítems del sidebar tienen página.

---

### Rutas faltantes (necesarias para el producto)

Rutas que deben existir en la Tenant Console pero no tienen ningún archivo en el repo:

| Ruta | Módulo | Bloquea |
|------|--------|---------|
| `/dashboard/media` | Media | Imágenes en catálogo |
| `/dashboard/inventory` | Inventario | Control de stock |
| `/dashboard/orders` | Pedidos | Shipping, métricas de negocio |
| `/dashboard/contacts` | Contactos | Historial de clientes |
| `/dashboard/knowledge-base` | Knowledge Base | Mejora contexto IA |
| `/dashboard/integrations` | Integraciones | MeLi, Envia |
| `/dashboard/shipping` | Shipping / Courier | Envíos con Envia |
| `/dashboard/metrics` | Métricas | KPIs operacionales |
| `/dashboard/audit` | Auditoría | Trazabilidad |
| `/dashboard/settings` | Configuración | RBAC, WABA, equipo |

---

### Rutas propuestas (sub-rutas a validar antes de implementar)

Sub-rutas que tiene sentido diseñar pero que requieren validación de producto:

```
/dashboard/catalog/[id]              → Detalle / edición de producto
/dashboard/catalog/[id]/variants     → Gestión de variantes
/dashboard/orders/[id]               → Detalle de pedido
/dashboard/shipping/quote            → Formulario de cotización
/dashboard/shipping/[id]             → Detalle de envío / tracking
/dashboard/contacts/[id]             → Perfil de contacto
/dashboard/settings/team             → Gestión de usuarios del equipo
/dashboard/settings/whatsapp         → Configuración WABA
/dashboard/settings/integrations     → Config por conector
```

> Estas rutas están propuestas — no implementarlas sin validar su diseño funcional primero.

---

### Navegación objetivo (Tenant Console completa)

```
Commerce Ops [logo]
│
├── Resumen                      🟡  /dashboard
├── Inbox / Conversaciones       ✅  /dashboard/inbox
├── Catálogo                     🟡  /dashboard/catalog
├── Media                        ❌  /dashboard/media
├── Inventario                   ❌  /dashboard/inventory
├── Pedidos                      ❌  /dashboard/orders
├── Contactos                    ❌  /dashboard/contacts
├── Knowledge Base               ❌  /dashboard/knowledge-base
├── Integraciones                ❌  /dashboard/integrations
├── Shipping / Courier           📋  /dashboard/shipping
├── Métricas                     ❌  /dashboard/metrics
├── Auditoría                    ❌  /dashboard/audit
└── Configuración                ❌  /dashboard/settings
    ├── Perfil
    ├── WhatsApp / WABA
    ├── Equipo
    └── Plan
```

---

## B. PLATFORM CONSOLE

### Estado actual

**No existe ningún archivo de ruta de Platform Console en el repo.**

No hay:
- Layout de platform console
- Archivos en `apps/web/app/platform/`
- Rutas `/platform/*`
- Roles de plataforma en DB
- Separación de auth para operadores de plataforma

---

### Rutas faltantes (Platform Console objetivo)

Todas las rutas de Platform Console son inexistentes. Las listamos como objetivo futuro:

| Ruta | Módulo | Estado |
|------|--------|--------|
| `/platform` | Overview Global | ❌ No existe |
| `/platform/tenants` | Tenants | ❌ No existe |
| `/platform/tenants/[id]` | Tenant Detail | ❌ No existe |
| `/platform/health` | Health Center | ❌ No existe |
| `/platform/integrations` | Integraciones Globales | ❌ No existe |
| `/platform/jobs` | Jobs / Queue Ops | ❌ No existe |
| `/platform/security` | Seguridad | ❌ No existe |
| `/platform/audit` | Auditoría Global | ❌ No existe |
| `/platform/billing` | Billing / Planes | ❌ No existe |
| `/platform/flags` | Feature Flags | ❌ No existe |
| `/platform/support` | Soporte Operativo | ❌ No existe |

---

### Navegación objetivo (Platform Console completa)

```
Platform Admin [logo]
│
├── Overview Global              ❌  /platform
├── Tenants                      ❌  /platform/tenants
│   └── Tenant Detail            ❌  /platform/tenants/[id]
├── Health Center                ❌  /platform/health
├── Integraciones Globales       ❌  /platform/integrations
├── Jobs / Queue Ops             ❌  /platform/jobs
├── Seguridad                    ❌  /platform/security
├── Auditoría Global             ❌  /platform/audit
├── Billing / Planes             ❌  /platform/billing
├── Feature Flags                ❌  /platform/flags
└── Soporte Operativo            ❌  /platform/support
```

---

## Separación técnica de consolas

### Middleware actual (`apps/web/middleware.ts`)

El middleware actual protege `/dashboard/*` redirigiendo a `/login` si no hay sesión.
No existe separación de rutas `/platform`.

### Separación requerida (objetivo)

```
middleware.ts debe:
  /dashboard/* → verificar sesión + rol tenant (owner/manager/agent)
  /platform/*  → verificar sesión + rol plataforma (platform_superadmin/support/ops)
```

Esto requiere:
1. Tabla o campo para roles de plataforma (no existe en DB)
2. Lógica de middleware diferenciada por path prefix
3. Layout separado para `/platform/*`

### Pregunta abierta de arquitectura (OQ-P01)

¿La Platform Console comparte la misma Next.js app que la Tenant Console, o es una app separada?

**Opciones**:
- a) **Misma app**, separada por path (`/dashboard/*` vs `/platform/*`) — más simple, ya usado
- b) **App separada** en `apps/platform/` — más limpia, más overhead de setup
- c) **Sub-dominio separado** (`platform.commerce-ops.com`) — mayor separación física

> Decisión pendiente de validación. Por simplicidad inicial se recomienda opción (a) con layout separado.

---

## Regla de expansión de navegación

No agregar ítems al sidebar de ninguna consola sin:
1. Que el módulo tenga una página funcional (aunque sea básica)
2. Que esté documentado en `admin-ui-modules.md`
3. Que el backend necesario esté identificado en `front-back-separation.md`

No crear rutas "placeholder" que muestren "Coming Soon" — produce confusión sobre qué está implementado.

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Detalle de cada módulo con evidencia en repo
- `docs/product/current-scope.md` — Stack real verificado
- `docs/architecture/front-back-separation.md` — Qué backend sustenta cada ruta
