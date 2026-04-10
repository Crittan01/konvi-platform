# Regla: Arquitectura de Navegación — Tenant Console
> Versión: 1.0 | Aprobada: 2026-04-10
> Esta regla es de cumplimiento obligatorio para cualquier agente que modifique el frontend.

## Regla N-01: Estructura de módulos aprobada

La Tenant Console tiene la siguiente estructura de navegación oficial.
**NO agregar módulos al sidebar sin seguir este mapa:**

```
NIVEL RAÍZ (siempre visibles en sidebar):
  Dashboard     /dashboard           roles: todos
  Inbox         /dashboard/inbox     roles: todos

GRUPOS EXPANDIBLES:
  Ventas        roles: todos
    Pedidos     /dashboard/orders
    Contactos   /dashboard/contacts
    Envíos      /dashboard/shipping

  Productos     roles: owner, manager
    Catálogo    /dashboard/catalog
    Inventario  /dashboard/inventory

  IA & Contenido  roles: owner, manager
    Base de Conocimiento  /dashboard/knowledge-base
    Media                 /dashboard/media

  Analítica     roles: owner, manager
    Métricas    /dashboard/metrics
    Auditoría   /dashboard/audit     roles: owner

  Configuración  roles: owner, manager
    General      /dashboard/settings      roles: owner
    Integraciones /dashboard/integrations roles: owner
```

## Regla N-02: Labels oficiales

NO cambiar estos labels sin actualizar primero este documento:

| Label en UI | Ruta |
|------------|------|
| Dashboard | /dashboard |
| Inbox | /dashboard/inbox |
| Pedidos | /dashboard/orders |
| Contactos | /dashboard/contacts |
| Envíos | /dashboard/shipping |
| Catálogo | /dashboard/catalog |
| Inventario | /dashboard/inventory |
| Base de Conocimiento | /dashboard/knowledge-base |
| Media | /dashboard/media |
| Métricas | /dashboard/metrics |
| Auditoría | /dashboard/audit |
| General | /dashboard/settings |
| Integraciones | /dashboard/integrations |

**Labels prohibidos** (reemplazados):
- ~~Resumen~~ → Dashboard
- ~~Inbox AI~~ → Inbox
- ~~Knowledge Base~~ → Base de Conocimiento
- ~~Configuración~~ → General (cuando es sub-item)

## Regla N-03: Cuándo usar tabs vs. sub-items en sidebar

✅ **Usar tabs dentro de la página** cuando:
- Son vistas alternativas del mismo conjunto de datos
- No tienen URL propia diferenciada
- Ejemplo: Dashboard tabs "Operaciones" / "Negocio"

✅ **Usar sub-item en sidebar** cuando:
- Tiene URL propia (`/dashboard/xxx`)
- Tiene propósito suficientemente diferenciado del módulo padre
- El usuario necesita navegar directamente desde cualquier parte de la app

## Regla N-04: RBAC en sidebar

El componente `SidebarClient` implementa RBAC en dos niveles:
1. **Nivel grupo**: si el usuario no tiene el rol, el grupo completo es invisible
2. **Nivel hijo**: cada hijo tiene su propio filtro de roles

Los roles son: `owner` > `manager` > `agent`
- `roles: []` = accesible por todos
- `roles: ['owner', 'manager']` = solo owner y manager
- `roles: ['owner']` = solo owner

## Regla N-05: Nuevo módulo → asignar grupo primero

Antes de crear un nuevo módulo, consultar `docs/architecture/nav-architecture.md`
para determinar bajo qué grupo pertenece. Seguir esta guía:

| Tipo de funcionalidad | Grupo |
|----------------------|-------|
| Operaciones de venta | Ventas |
| Gestión de productos | Productos |
| Contenido para IA | IA & Contenido |
| Reportes / análisis | Analítica |
| Ajustes de cuenta | Configuración |

## Regla N-06: Archivo fuente de verdad

El array `NAV_ITEMS` en `apps/web/app/dashboard/sidebar-client.tsx`
es la **única fuente de verdad** para la navegación.
Cambiar labels, rutas o grupos SOLO ahí. No hay otra configuración.
