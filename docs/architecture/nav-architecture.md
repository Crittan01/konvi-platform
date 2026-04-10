# Arquitectura de Navegación — Tenant Console
> Documento de arquitectura aprobado. Última actualización: 2026-04-10.
> Este archivo es fuente de verdad para la estructura del sidebar y módulos.

## Decisión de diseño

La Tenant Console usa navegación por **grupos expandibles** en el sidebar.

**Regla fundamental:**
- **Sub-item en sidebar** = módulo con URL propia y propósito claramente diferenciado
- **Tabs dentro de una página** = vistas alternativas del mismo dato → NO crear rutas separadas

Esto resuelve dos problemas del diseño anterior:
1. Todos los módulos estaban al mismo nivel jerárquico → cognitive overload
2. Algunos módulos mezclan frecuencia de uso (diaria vs. ocasional)

---

## Mapa de navegación oficial

```
📍 Ruta raíz     /dashboard
   Dashboard      Operacional en tiempo real — tabs: Operaciones / Negocio

📍 Ruta raíz     /dashboard/inbox
   Inbox          Conversaciones WhatsApp (antes: "Inbox AI")

▼ GRUPO: Ventas   /dashboard/orders, /contacts, /shipping
   Pedidos         Gestión de órdenes con filtros y estados
   Contactos       CRM con consentimiento Habeas Data
   Envíos          Cotización y tracking vía Envia (antes: nivel raíz)

▼ GRUPO: Productos   /dashboard/catalog, /inventory   [owner + manager]
   Catálogo        Multi-variante con edición inline
   Inventario      Ajustes de stock y umbral de alerta

▼ GRUPO: IA & Contenido   /dashboard/knowledge-base, /media   [owner + manager]
   Base de Conocimiento    Documentos para el contexto de Gemini
                           (antes: "Knowledge Base" en inglés)
   Media                   Imágenes subidas a Supabase Storage

▼ GRUPO: Analítica   /dashboard/metrics, /audit   [owner + manager]
   Métricas        Análisis histórico por período (7/30/90 días)
   Auditoría       Log de eventos por entidad y usuario   [owner only]

▼ GRUPO: Configuración   /dashboard/settings, /integrations   [owner + manager]
   General         Tenant info, logo, equipo, Telegram, dirección de origen
                   (antes: "Configuración" era el módulo completo)
   Integraciones   Conectores Envia y MeLi   [owner only]
                   (antes: nivel raíz — ahora bajo Config)
```

---

## Cambios respecto al diseño anterior

| Cambio | Anterior | Actual | Razón |
|--------|----------|--------|-------|
| Nombre | "Resumen" | Dashboard | Término estándar de industria; la ruta ya era `/dashboard` |
| Nombre | "Inbox AI" | Inbox | El AI es implícito; nombre más limpio |
| Nombre | "Knowledge Base" | Base de Conocimiento | Consistencia de idioma |
| Posición | Envíos al nivel raíz | Ventas > Envíos | Un envío es consecuencia de un pedido |
| Posición | Integraciones al nivel raíz | Config > Integraciones | Las integraciones son configuración de cuenta |
| Propósito | Dashboard ≈ Métricas (ambos mostraban datos) | Dashboard = real-time operacional; Métricas = histórico | Diferenciación clara de propósito |

---

## RBAC en navegación

```
Grupo/Item          owner  manager  agent
──────────────────────────────────────────
Dashboard           ✅     ✅       ✅
Inbox               ✅     ✅       ✅
Ventas (grupo)      ✅     ✅       ✅
  Pedidos           ✅     ✅       ✅
  Contactos         ✅     ✅       ✅
  Envíos            ✅     ✅       ✅
Productos (grupo)   ✅     ✅       ❌
  Catálogo          ✅     ✅       ❌
  Inventario        ✅     ✅       ❌
IA & Contenido      ✅     ✅       ❌
  Base Conocimiento ✅     ✅       ❌
  Media             ✅     ✅       ❌
Analítica (grupo)   ✅     ✅       ❌
  Métricas          ✅     ✅       ❌
  Auditoría         ✅     ❌       ❌
Configuración       ✅     ✅       ❌
  General           ✅     ❌       ❌
  Integraciones     ✅     ❌       ❌
```

---

## Comportamiento del sidebar

1. **Auto-expand**: el grupo que contiene la ruta activa se abre automáticamente al cargar
2. **Indicador activo**: punto ámbar en items activos y en grupo colapsado con hijo activo
3. **RBAC dual**: el grupo se filtra si `roles` del grupo no incluye el rol del usuario;
   además cada hijo tiene su propio filtro de roles
4. **Mobile**: drawer desde la izquierda con overlay + cierre automático al navegar
5. **Animación**: max-height + opacity transition para el collapse/expand

---

## Implementación

**Archivo:** `apps/web/app/dashboard/sidebar-client.tsx`

Tipos principales:
```typescript
type NavLeaf = { kind: 'leaf'; href; label; icon; roles }
type NavGroup = { kind: 'group'; id; label; icon; roles; children: NavLeaf[] }
```

El array `NAV_ITEMS: (NavLeaf | NavGroup)[]` es la única fuente de verdad
para agregar, renombrar o mover módulos en la navegación.

---

## Próximos módulos planeados

Cuando se implementen nuevos módulos, seguir esta guía de asignación de grupo:

| Módulo futuro | Grupo asignado | Razón |
|---------------|---------------|-------|
| Campañas WhatsApp | Ventas | Es una acción de venta |
| Automatizaciones / Flows | IA & Contenido | Es lógica de IA |
| Reportes exportables | Analítica | Es análisis |
| Webhooks salientes | Configuración | Es configuración de cuenta |
| Zona horaria / Branding | Configuración > General | Es config de tenant |
