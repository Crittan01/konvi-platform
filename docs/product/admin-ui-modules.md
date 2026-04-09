# Módulos de Interfaz Administrativa — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 2 — B.4-B.11 expandidos con Propósito y Dependencia backend)

Este documento define los módulos visibles de ambas consolas con **evidencia real del repo**.

**Estados**:
- ✅ **Implementado** — existe en código y funciona
- 🟡 **Parcial** — existe pero incompleto o limitado
- 📋 **Diseñado** — documentado, no hay código aún
- ❌ **Pendiente** — no existe ni diseñado en detalle

---

## A. TENANT CONSOLE

---

### A.1 — Inicio / Dashboard

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard` |
| **Estado** | 🟡 Parcial |
| **Propósito** | Página de inicio del tenant. Muestra contexto de sesión y actividad operacional. |
| **Submódulos** | Identidad de sesión, empresa acoplada (tenant), accesos rápidos (futuro), métricas resumen (futuro) |
| **Estado actual real** | Muestra email del usuario y nombre del tenant. Sin métricas, sin alertas, sin KPIs. |
| **Evidencia en repo** | `apps/web/app/dashboard/page.tsx` — 2 cards estáticas con email y tenant name |
| **Dependencia backend** | `tenant_users` join `tenants` — ya implementado. Métricas futuras requieren queries de agregación |
| **Prioridad** | Media — funcional para el estado actual, no bloquea otras fases |

---

### A.2 — Inbox / Conversaciones

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/inbox` |
| **Estado** | ✅ Implementado |
| **Propósito** | Bandeja de conversaciones WhatsApp con AI activa, takeover humano y hilo visual. |
| **Submódulos actuales** | Lista de conversaciones, hilo de mensajes, human takeover / volver al bot, Realtime |
| **Submódulos faltantes** | Filtros por estado, búsqueda por teléfono, notas internas, asignación de agente, adjuntos |
| **Estado actual real** | Lista conversaciones del tenant. Hilo inbound/outbound. Botón takeover. Realtime via Supabase. |
| **Evidencia en repo** | `apps/web/app/dashboard/inbox/page.tsx` — ~200 líneas, Supabase Realtime, status update |
| **Dependencia backend** | `conversations` + `messages` — tablas existen. Supabase Realtime activo. |
| **Prioridad** | Alta — módulo core del producto. Funcional hoy. |

---

### A.3 — Catálogo

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/catalog` |
| **Estado** | 🟡 Parcial |
| **Propósito** | Gestión de productos del tenant: listado, creación, variantes, precios, stock. |
| **Submódulos actuales** | Listado de productos (con primera variante), formulario de creación (título, desc, precio, stock) |
| **Submódulos faltantes** | Editar producto, eliminar (soft delete), gestión de múltiples variantes, imágenes, filtros, paginación, sync MeLi |
| **Estado actual real** | Crea producto + una variante fija "Standard". Lista solo primera variante de cada producto. No hay edición ni delete desde UI. |
| **Evidencia en repo** | `apps/web/app/dashboard/catalog/page.tsx` — Server Action de inserción, Supabase directo (no services/api) |
| **Dependencia backend** | `products` + `product_variations` — tablas existen. No usa `services/api` para lectura (Supabase directo). |
| **Prioridad** | Alta — necesita variantes y edición antes de ser útil en producción |

---

### A.4 — Media

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/media` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Gestión de imágenes y archivos vinculados al catálogo y conversaciones. |
| **Submódulos** | Subir imagen, listar media por tenant, asociar media a producto, eliminar |
| **Estado actual real** | No existe. Ningún archivo en el repo. |
| **Evidencia en repo** | Ninguna |
| **Dependencia backend** | Supabase Storage (buckets por tenant) + políticas de acceso. No configurado aún. |
| **Prioridad** | Baja — no bloquea fases core |

---

### A.5 — Inventario

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/inventory` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Control de stock por variante, alertas de bajo stock, historial de movimientos. |
| **Submódulos** | Vista de stock por variante, ajuste manual de stock, alertas configurables, historial de movimientos |
| **Estado actual real** | No existe. El campo `stock_quantity` existe en `product_variations` pero no hay UI de inventario. |
| **Evidencia en repo** | `product_variations.stock_quantity` en `packages/db/migrations/00002_catalog_schema.sql` |
| **Dependencia backend** | `product_variations` (existe). Tabla `stock_movements` (no existe). Endpoint PUT stock en `services/api` (no existe). |
| **Prioridad** | Media — necesario para Fase 9 |

---

### A.6 — Pedidos

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/orders` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Registro, seguimiento y gestión de órdenes del tenant. Vínculo con conversaciones y shipping. |
| **Submódulos** | Listado de pedidos, detalle de pedido, crear pedido manual, cambiar estado, vínculo con conversación, vínculo con envío |
| **Estado actual real** | No existe. No hay tabla `orders` en DB. |
| **Evidencia en repo** | Ninguna |
| **Dependencia backend** | Tablas `orders` + `order_items` (no creadas). Endpoints CRUD en `services/api` (no creados). Conector MeLi (Fase 8). |
| **Prioridad** | Alta — módulo core del negocio. Bloquea Shipping y métricas de conversión. |

---

### A.7 — Contactos

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/contacts` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Base de clientes del tenant con historial de conversaciones y pedidos. |
| **Submódulos** | Listado de contactos, perfil de contacto, historial de interacciones, crear/editar contacto |
| **Estado actual real** | No existe. Los clientes solo se identifican por `customer_phone` en `conversations`. |
| **Evidencia en repo** | `conversations.customer_phone` en `packages/db/migrations/00003_conversational_schema.sql` |
| **Dependencia backend** | Tabla `contacts` (no creada). Endpoint en `services/api` (no creado). |
| **Prioridad** | Media — deseable pero no bloquea core |

---

### A.8 — Knowledge Base

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/knowledge-base` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Documentos y respuestas frecuentes que alimentan el contexto del LLM para este tenant. |
| **Submódulos** | Crear/editar/eliminar documentos, categorización, estado (activo/inactivo), búsqueda |
| **Estado actual real** | No existe. El orchestrator solo usa el catálogo como contexto. |
| **Evidencia en repo** | `docs/ai/rag.md` — diseño del pipeline RAG, no implementado |
| **Dependencia backend** | Tabla `kb_documents` (no creada). Pipeline RAG / embeddings (no implementado). `tools/kb_tool.py` (no existe). |
| **Prioridad** | Baja — mejora calidad IA pero no bloquea core |

---

### A.9 — Integraciones

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/integrations` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Configuración y estado de conectores activos por tenant: MeLi, Envia, Telegram. |
| **Submódulos** | Lista de conectores disponibles, conectar/desconectar conector, estado de sincronización, config por conector |
| **Estado actual real** | No existe. No hay tabla de config de integraciones por tenant. |
| **Evidencia en repo** | Ninguna |
| **Dependencia backend** | Tabla `tenant_integrations` (no creada). OAuth flow MeLi (no implementado). |
| **Prioridad** | Alta — bloquea MeLi y Envia |

---

### A.10 — Shipping / Courier

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/shipping` |
| **Estado** | 📋 Diseñado |
| **Propósito** | Cotización de envíos, selección de carrier, pickup, historial, tracking. Basado en Envia. |
| **Submódulos** | Dashboard de envíos, cotizar envío (formulario), historial de cotizaciones, pickups, tracking (futuro), labels (futuro), manifests (futuro) |
| **Estado actual real** | No existe ningún archivo en el repo. Solo diseño en `docs/integrations/courier-envia.md`. |
| **Evidencia en repo** | Ninguna — solo documentación |
| **Dependencia backend** | `services/connector-envia` (no existe). Tabla `shipments` (no existe). Tabla `orders` (no existe). Validar modelo auth Envia antes de implementar (PV-03). |
| **Prioridad** | Media — depende de Pedidos (A.6) y del connector Envia |

---

### A.11 — Métricas

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/metrics` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Dashboards operacionales: mensajes/día, tiempo de respuesta IA, conversiones, pedidos. |
| **Submódulos** | Gráfica de mensajes, tiempo de respuesta, conversaciones cerradas, pedidos por período |
| **Estado actual real** | No existe. |
| **Evidencia en repo** | Ninguna |
| **Dependencia backend** | Queries de agregación sobre `messages` + `conversations` (tablas existen). `orders` (no existe). |
| **Prioridad** | Baja — requiere datos de pedidos para ser útil |

---

### A.12 — Auditoría

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/audit` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Log de acciones del tenant: quién hizo qué, cuándo, en qué recurso. |
| **Submódulos** | Log de acciones con filtros por usuario, tipo de acción, fecha, recurso |
| **Estado actual real** | No existe. Tabla `audit_log` no creada. |
| **Evidencia en repo** | Riesgo R-10 activo en `docs/risks/risk-register.md` |
| **Dependencia backend** | Tabla `audit_log` (no creada). Triggers o escritura explícita desde API. |
| **Prioridad** | Media — necesario antes de producción real |

---

### A.13 — Configuración

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/settings` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Ajustes del tenant: WABA, equipo, notificaciones, perfil, plan. |
| **Submódulos** | Perfil de empresa, configuración WABA, gestión de usuarios del equipo (RBAC), notificaciones, plan |
| **Estado actual real** | No existe. El WABA ID se configura directamente en DB. No hay UI de configuración. |
| **Evidencia en repo** | `tenants.meta_waba_id` en DB. `tenant_users.role` en DB. Sin UI correspondiente. |
| **Dependencia backend** | Endpoints de settings en `services/api` (no existen). RBAC enforceado (no implementado — Riesgo R-09). |
| **Prioridad** | Alta — RBAC y gestión de equipo son necesarios para tenants reales |

---

## B. PLATFORM CONSOLE

> **Estado global: ❌ No implementada.**
> No existe ningún archivo de código, ruta ni layout de Platform Console en el repositorio.
> Los módulos que siguen son la definición objetivo.

---

### B.1 — Overview Global

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Vista agregada de todos los tenants: actividad, conversaciones, alertas de salud. |
| **Dependencia backend** | Queries cross-tenant con service_role. Endpoint platform-only en `services/api`. |
| **Prioridad** | Baja — solo después de Tenant Console completa |

---

### B.2 — Tenants

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/tenants` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Lista y gestión de tenants: altas, bajas, planes, estado. |
| **Dependencia backend** | Tabla `tenants` (existe). Endpoints platform-admin en `services/api` (no existen). |
| **Prioridad** | Baja |

---

### B.3 — Tenant Detail

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/tenants/[id]` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Vista de soporte de un tenant específico (auditado). |
| **Dependencia backend** | Acceso de soporte auditado. `audit_log` (no existe). |
| **Prioridad** | Baja |

---

### B.4 — Health Center

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/health` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Estado en tiempo real de todos los servicios: connector-whatsapp, ai-orchestrator, api, Supabase, Render. |
| **Dependencia backend** | Endpoints `/health` de cada servicio (existen en connector y orchestrator). Agregador en `services/api` o endpoint separado. No requiere tablas nuevas. |
| **Prioridad** | Baja |

---

### B.5 — Integraciones Globales

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/integrations` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Configuración de conectores a nivel de plataforma (no por tenant): credenciales globales de Envia, configuración de Meta App, etc. |
| **Dependencia backend** | Tabla `platform_config` (no existe). Endpoints platform-only en `services/api` (no existen). |
| **Prioridad** | Baja |

---

### B.6 — Jobs / Queue Ops

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/jobs` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Monitoreo del AI Orchestrator: mensajes procesados, errores, latencia del polling loop, colas pendientes. |
| **Dependencia backend** | Endpoint `/status` del orchestrator (existe). Métricas agregadas en `services/api` (no existen). |
| **Prioridad** | Baja |

---

### B.7 — Seguridad

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/security` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Gestión de tokens de plataforma, log de accesos cross-tenant, roles de operadores de plataforma. |
| **Dependencia backend** | Tabla `platform_users` (no existe). Tabla `platform_audit_log` o extensión de `audit_log` (no existe). |
| **Prioridad** | Baja |

---

### B.8 — Auditoría Global

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/audit` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Log de todas las acciones en la plataforma: acciones de tenants, accesos de soporte, cambios de configuración global. |
| **Dependencia backend** | Tabla `audit_log` (no existe — necesaria también en A.12). Extensión con `actor_type = platform` para acciones de operadores de plataforma. |
| **Prioridad** | Baja |

---

### B.9 — Billing / Planes

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/billing` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Gestión de planes de suscripción por tenant: plan activo, fechas, uso, estado de pago. |
| **Dependencia backend** | Tabla `tenant_plans` (no existe). Posible integración con Stripe (no definida). Endpoints platform-admin en `services/api` (no existen). |
| **Prioridad** | Baja |

---

### B.10 — Feature Flags

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/flags` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Control de features habilitadas por tenant o por plan: activar/desactivar módulos sin deploy. |
| **Dependencia backend** | Tabla `feature_flags` (no existe). Integración con la lógica de auth del frontend para mostrar/ocultar módulos. |
| **Prioridad** | Baja |

---

### B.11 — Soporte Operativo

| Campo | Valor |
|-------|-------|
| **Consola** | Platform Console |
| **Ruta** | `/platform/support` |
| **Estado** | ❌ Pendiente |
| **Propósito** | Herramientas internas para escalamientos: vista de tenant en modo soporte (auditado), notas internas, historial de incidencias. |
| **Dependencia backend** | Lógica de acceso de soporte auditado (ver `personas-and-consoles.md`). Tabla `audit_log` (no existe). Requiere registro explícito de cada acceso cross-tenant. |
| **Prioridad** | Baja |

> Ninguno de los módulos B.4-B.11 tiene código en el repo.
> **Prerrequisito absoluto de todos**: la autenticación y roles de plataforma (`platform_users`) deben existir antes de implementar cualquier módulo de Platform Console. Ver `docs/architecture/front-back-separation.md` sección B.

---

## Regla de actualización de este documento

Actualizar cada vez que:
- Un módulo cambia de estado (❌/📋 → 🟡 → ✅)
- Se descubren nuevas capacidades reales en código
- Se agregan submódulos a la definición
- Cambia la prioridad por decisión de roadmap

---

## Documentos relacionados

- `docs/product/current-scope.md` — Estado del stack y evidencia general
- `docs/product/navigation-map.md` — Rutas reales vs faltantes vs propuestas
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend con orden de implementación
