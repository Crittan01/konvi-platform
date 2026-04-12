# Módulos de Interfaz Administrativa — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 4 — visión objetivo por módulo añadida; Habeas Data documentado; MeLi disconnect gap registrado)

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
| **Estado actual real** | 4 KPI cards (totales: conversaciones, pedidos, contactos, productos activos) + quick links RBAC-aware. Sin gráficas, sin tendencias, sin alertas. |
| **Evidencia en repo** | `apps/web/app/dashboard/page.tsx` — Promise.all para 4 counts + quick links |
| **Dependencia backend** | `tenant_users` join `tenants` — ya implementado. Métricas futuras requieren queries de agregación |
| **Visión objetivo** | Tabs: (1) **Operaciones** — conversaciones activas, takeovers humanos, pedidos pendientes, alertas stock bajo clickables; (2) **Negocio** — KPIs con tendencia temporal, gráfica de actividad diaria, distribución pedidos por estado, top productos. Ver `docs/product/module-design-decisions.md#a1`. |
| **Prioridad** | Media — funcional para el estado actual, no bloquea otras fases |

---

### A.2 — Inbox / Conversaciones

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/inbox` |
| **Estado** | ✅ Implementado |
| **Propósito** | Bandeja de conversaciones WhatsApp con AI activa, takeover humano y hilo visual. |
| **Submódulos actuales** | Lista de conversaciones, hilo de mensajes, human takeover / volver al bot, envío de mensajes por agente (ChatInput), Realtime |
| **Submódulos faltantes** | Filtros por estado (avanzados), notas internas, asignación de agente, adjuntos |
| **Estado actual real** | Lista conversaciones del tenant. Hilo inbound/outbound. Botón takeover. Envío manual de agente habilitado llamando al API Gateway. Realtime via Supabase completo. |
| **Evidencia en repo** | `apps/web/app/dashboard/inbox/page.tsx` — Supabase Realtime, ChatInput implementado. |
| **Dependencia backend** | `conversations` + `messages` — tablas existen. Supabase Realtime activo. Endpoint `/api/v1/conversations/{id}/send`. |
| **Gap crítico** | ✅ Resuelto (Fase 11.3). El agente ya puede realizar takeover y enviar respuestas escritas directamente al cliente por WhatsApp desde la UI. |
| **Visión objetivo** | Filtros por estado avanzado. Búsqueda por teléfono. Notas internas. |
| **Prioridad** | Completada (Funcional Nivel Pro). |

---

### A.3 — Catálogo

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/catalog` |
| **Estado** | 🟡 Parcial |
| **Propósito** | Gestión de productos del tenant: listado, creación, variantes, precios, stock. |
| **Submódulos actuales** | Listado de productos, creación, edición, soft delete (status=inactive), RBAC owner/manager |
| **Submódulos faltantes** | Gestión de múltiples variantes (UI), paginación, sync con MeLi |
| **Estado actual real** | Crea producto + una variante "Standard". Edición y soft delete implementados. RBAC visual en sidebar. |
| **Evidencia en repo** | `apps/web/app/dashboard/catalog/page.tsx` — Server Actions, Supabase directo + `services/api` products router |
| **Dependencia backend** | `products` + `product_variations` + `services/api/routers/products.py` (Fase 8). RBAC enforceado. |
| **Visión objetivo** | Formulario N variantes con atributos dinámicos. Importación desde MeLi ID/URL (pre-fill del formulario). Carga masiva CSV con schema por categoría. Búsqueda + paginación. |
| **Prioridad** | Media — funcional. Variantes múltiples y paginación son deuda técnica. |

---

### A.4 — Media

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/media` |
| **Estado** | ✅ Implementado |
| **Propósito** | Gestión de imágenes y archivos del tenant vinculados al catálogo y conversaciones. |
| **Submódulos actuales** | Upload, listado, eliminar, copiar URL pública |
| **Submódulos faltantes** | Asociación directa a productos, filtros por tipo/fecha |
| **Estado actual real** | Upload (JPEG/PNG/WebP/GIF ≤ 5MB), listado desde Supabase Storage, delete, copy URL. Bucket: `tenant-media`. Sin preview visual, sin asociación a productos. |
| **Evidencia en repo** | `apps/web/app/dashboard/media/page.tsx` (Server) + `media-client.tsx` (Client Component) |
| **Dependencia backend** | Supabase Storage bucket `tenant-media`. RLS por carpeta: `(storage.foldername(name))[1] = auth.uid()`. |
| **Visión objetivo** | Media como biblioteca centralizada. Preview thumbnails en galería. Vinculación de imágenes a productos/variantes (desde Media o desde Catálogo). Filtros por estado de vinculación. NO fusionar con Inventario — mantener como módulo separado pero integrado. |
| **Prioridad** | Baja — funcional. Asociación a productos es mejora futura. |

---

### A.5 — Inventario

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/inventory` |
| **Estado** | ✅ Implementado |
| **Propósito** | Control de stock por variante, alertas de bajo stock, historial de movimientos. |
| **Submódulos actuales** | Stock por variación con atributos JSONB, alertas stock bajo (≤5), formulario ajuste de stock |
| **Submódulos faltantes** | Alertas configurables por umbral, historial paginado de movimientos, integración bidireccional con MeLi |
| **Estado actual real** | Lista stock por variante. Alerta automática ≤5 (hardcoded). Ajuste inserta en `stock_movements` con delta + reason. |
| **Evidencia en repo** | `apps/web/app/dashboard/inventory/page.tsx` — Server Actions, Supabase directo |
| **Dependencia backend** | `product_variations` + `stock_movements` (migración `20260409240000`). RLS por tenant. |
| **Visión objetivo** | Umbral de alerta configurable por tenant (no hardcoded en 5). Historial paginado de movimientos. Decremento automático al confirmar pedido. Sync MeLi bidireccional. Indicador visual de sincronización con MeLi por variante. |
| **Prioridad** | Media — funcional. Configuración de umbrales y sync MeLi son mejoras futuras. |

---

### A.6 — Pedidos

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/orders` |
| **Estado** | ✅ Implementado |
| **Propósito** | Registro, seguimiento y gestión de órdenes del tenant. Vínculo con contactos y shipping. |
| **Submódulos actuales** | Listado de pedidos (paginación cliente y searchbox), detalle, cambio de estado transicional, formulario nuevo pedido con async guard, vínculo con contacto y envío |
| **Submódulos faltantes** | Vínculo directo con conversación WhatsApp, sync bidireccional MeLi |
| **Estado actual real** | UI App-like con `<OrdersManager />`. Paginación fluida, búsqueda local instantánea. Pedidos entran via MeLi webhook o manualmente via form UI. Servidor unificado action para actualizar estado y cancelar. |
| **Evidencia en repo** | `apps/web/app/dashboard/orders/_components/orders-manager.tsx` + API routers |
| **Dependencia backend** | `orders` + `order_items`. `GET/POST /api/v1/orders`, `PATCH /orders/{id}`. |
| **Visión objetivo** | Vinculación opcional a conversación Inbox. Relación con Envíos: `pedido → tiene shipment` (ver `module-design-decisions.md#a6`). Sync MeLi bidireccional final. |
| **Nota técnica** | Se utiliza paginación Client Side in-memory extrayendo 500 ítems para reducir latencias, protegido con `useTransition`. |
| **Prioridad** | Completada (Funcional Nivel Pro). Creación manual desde UI funcional. |

---

### A.7 — Contactos

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/contacts` |
| **Estado** | ✅ Implementado |
| **Propósito** | Base de clientes del tenant con historial de conversaciones y pedidos. |
| **Submódulos actuales** | Listado de contactos paginado en cliente, búsqueda instantánea texto, perfil editable nativo |
| **Submódulos faltantes** | Historial ampliado de pedidos por contacto en modal, historial deep link de conversaciones por contacto |
| **Estado actual real** | Componente `<ContactsManager />` implementado con búsqueda/filtros instantáneos (Habeas Data). Creación y edición manual optimizada. Auto-creación API lista. |
| **Evidencia en repo** | `apps/web/app/dashboard/contacts/_components/contacts-manager.tsx` + `services/api/routers/contacts.py` |
| **Dependencia backend** | `contacts` (migración `20260409220000`). `GET/POST /api/v1/contacts`. |
| **Habeas Data Colombia** | ⚖️ El filtro y registro de `consent_given` (autorizado) ahora son nativos. Ley 1581 cubierta en UX. |
| **Visión objetivo** | Vista de perfil con modal de historial cruzado (pedidos totales + conversaciones activas). |
| **Prioridad** | Completada (Funcional Nivel Pro). Historial modal es mejora futura fase >13. |

---

### A.8 — Knowledge Base

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/knowledge-base` |
| **Estado** | ✅ Implementado |
| **Propósito** | Documentos y respuestas frecuentes que alimentan el contexto del LLM para este tenant. |
| **Submódulos actuales** | Crear/editar/eliminar documentos, categorías (faq/politica/negocio/producto/general), toggle activo/inactivo |
| **Submódulos faltantes** | Búsqueda interna, RAG con embeddings (pgvector), visualización de uso en conversaciones |
| **Estado actual real** | CRUD completo con Server Actions. KB inyectada en system prompt del Orchestrator como secciones markdown. Sin pgvector (diferido). |
| **Evidencia en repo** | `apps/web/app/dashboard/knowledge-base/page.tsx` + `services/ai-orchestrator/tools/kb_tool.py` |
| **Dependencia backend** | `kb_documents` (migración `20260409250000`). `kb_tool.py` + `orchestrator.py` (asyncio.gather). |
| **Visión objetivo ("El Giro")** | RAG real con embeddings (pgvector) — solo documentos relevantes a la consulta se inyectan en el prompt, no toda la KB. Prerequisito: verificar pgvector disponible (OQ-T03). Interfaz: vista previa de inyección, indicador de "última vez usado", importación desde PDF/URL (futuro). |
| **Prioridad** | Media — funcional. pgvector/RAG real queda como deuda técnica (PV-04). |

---

### A.9 — Integraciones

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/integrations` |
| **Estado** | ✅ Implementado |
| **Propósito** | Configuración y estado de conectores activos por tenant: MeLi, Envia. |
| **Submódulos actuales** | Estado MeLi (conectado/desconectado), OAuth MeLi, conectar/desconectar Envia (API key), estado de integraciones |
| **Submódulos faltantes** | Telegram, estado de sincronización en tiempo real, logs de errores por integración |
| **Estado actual real** | MeLi OAuth 2.0 per-tenant (solo conectar — sin desconectar). Envia con Bearer token per-tenant (conectar + desconectar). Tokens en `tenant_integrations`. |
| **Evidencia en repo** | `apps/web/app/dashboard/integrations/page.tsx` + `services/api/routers/integrations.py` + `integrations/meli_client.py` + `integrations/envia_client.py` |
| **Dependencia backend** | `tenant_integrations` (migración `20260409220000`). OAuth MeLi callback. Envia Bearer per-tenant. |
| **Gap crítico** | ⚠️ **Botón "Desconectar MeLi" no existe** en UI. Una vez conectada la cuenta MeLi, el tenant no puede desconectarla. Requiere: `DELETE /api/v1/integrations/mercadolibre` + botón en UI. |
| **Visión objetivo** | Botón desconectar MeLi. Estado de última sincronización exitosa por integración. Log básico de errores por conector. |
| **Prioridad** | Alta — funcional. Telegram y logs de sync son mejoras futuras. |

---

### A.10 — Shipping / Courier

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/shipping` |
| **Estado** | 🟡 Parcial — Fase Inicial operativa |
| **Propósito** | Cotización de envíos, selección de carrier, historial, pickup, tracking. Basado en Envia. |
| **Submódulos actuales** | Historial de cotizaciones + envíos, banner cuando Envia no conectado, visualización de estados |
| **Submódulos faltantes** | Formulario interactivo de cotización desde UI (Client Component), labels, pickups, tracking, manifests |
| **Estado actual real** | UI muestra historial de `shipments`. Envia Sandbox conectado (Empresa #5017). Cotización disponible via `POST /api/v1/shipping/quote` pero sin formulario interactivo en UI todavía. |
| **Evidencia en repo** | `apps/web/app/dashboard/shipping/page.tsx` + `services/api/routers/shipping.py` + `services/api/integrations/envia_client.py` |
| **Dependencia backend** | `shipments` (migración `20260409230000`). `tenant_integrations` + `envia_client.py`. PV-03 resuelto: Bearer per-tenant. |
| **Relación con Pedidos** | El envío se **crea desde un pedido** (botón "Crear envío" en detalle de pedido). Envíos muestra el historial cross-order. No son duplicados — son complementarios. |
| **Visión objetivo** | Formulario de cotización interactivo (tabla de opciones carrier/precio tras cotizar). Selección de carrier persiste `selected_rate`. Prerequisito: dirección de origen en Configuración. Fases 2-3: labels, tracking, pickup (planificadas). |
| **Prioridad** | Media — Backend operativo. Formulario UI interactivo es la deuda inmediata. Label/pickup/tracking son Fase 2 de Envia. |

---

### A.11 — Métricas

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/metrics` |
| **Estado** | ✅ Implementado |
| **Propósito** | Dashboards operacionales: mensajes, conversaciones, pedidos, productos. |
| **Submódulos actuales** | 4 KPI cards (mensajes 30d, conversaciones, pedidos, contactos), pedidos por estado, top 5 productos por cantidad/revenue |
| **Submódulos faltantes** | Gráficas de tendencia, filtros por período, métricas de tiempo de respuesta IA, conversión por canal |
| **Estado actual real** | Queries paralelas con `Promise.all` sobre Supabase directo. 4 KPIs + 2 listas (pedidos por estado + top 5 productos). Todo estático, período fijo 30 días. Sin gráficas. |
| **Evidencia en repo** | `apps/web/app/dashboard/metrics/page.tsx` — Server Component con queries paralelas |
| **Dependencia backend** | `messages`, `conversations`, `orders`, `order_items`, `contacts`, `products` — todas existen. |
| **Diferencia con Dashboard** | Dashboard = urgencia operacional + resumen ejecutivo. Métricas = módulo analítico profundo con filtros temporales. Son complementarios, no redundantes. |
| **Visión objetivo** | Filtro de período (hoy/semana/mes/3 meses/personalizado). Gráficas de tendencia (recharts). Métricas de IA (% takeover vs bot). Tasa de conversión (conversaciones → pedidos). Exportación CSV. |
| **Prioridad** | Media — funcional con datos actuales. Gráficas y filtros son mejoras futuras. |

---

### A.12 — Auditoría

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/audit` |
| **Estado** | ✅ Implementado |
| **Propósito** | Log de acciones del tenant: quién hizo qué, cuándo, en qué recurso. |
| **Submódulos actuales** | Filtro por entity_type (badges como links), paginación 25/página, payload JSONB expandible con `<details>` |
| **Submódulos faltantes** | Filtro por usuario, filtro por rango de fechas, exportación CSV |
| **Estado actual real** | Lista `audit_log` del tenant. Filtros por entity_type via query params. User email snapshot en cada entrada. Paginación 25/página. `<details>` expandible por payload. |
| **Evidencia en repo** | `apps/web/app/dashboard/audit/page.tsx` — Server Component, paginación, filtros |
| **Dependencia backend** | `audit_log` (migración `20260409260000`). Escritura explícita desde API (no triggers). RLS por tenant. |
| **Visión objetivo** | Filtro por usuario (user_email). Filtro por rango de fechas. Descripción legible de la acción (no solo código). Exportación CSV del log filtrado. |
| **Prioridad** | Media — funcional. Filtros adicionales y exportación son mejoras futuras. |

---

### A.13 — Configuración

| Campo | Valor |
|-------|-------|
| **Consola** | Tenant Console |
| **Ruta** | `/dashboard/settings` |
| **Estado** | ✅ Implementado |
| **Propósito** | Ajustes del tenant: perfil de empresa, WABA, equipo, notificaciones. |
| **Submódulos actuales** | Perfil de empresa, WABA ID editable, gestión de usuarios del equipo (RBAC), notificaciones |
| **Submódulos faltantes** | Cambio de contraseña desde UI, gestión de planes/billing, integraciones de notificación (email/Telegram) |
| **Estado actual real** | Formulario de perfil + WABA. Lista del equipo con roles. `GET/PUT /api/v1/settings`, `GET/POST/DELETE /team`. `get_tenant_team()` función SECURITY DEFINER para exponer emails de auth.users. Sin branding, sin cambio de contraseña, sin dirección de origen. |
| **Evidencia en repo** | `apps/web/app/dashboard/settings/page.tsx` + `services/api/routers/settings.py` |
| **Dependencia backend** | `tenants`, `tenant_users`, `notification_settings` (migración `20260409220000`). `get_tenant_team()` función SQL. |
| **Visión objetivo (branding)** | Logo del tenant visible en el sidebar de la consola (upload a Supabase Storage, campo `logo_url` en `tenants`). Color primario opcional. Esto hace que el tenant sienta la plataforma como "suya". Estos detalles pequeños suman mucho valor percibido. |
| **Visión objetivo (operaciones)** | Dirección de origen de envíos (default para cotizaciones Envia). Cambio de contraseña. Invitaciones al equipo por email. Zona horaria del tenant para métricas. |
| **Prioridad** | Alta — funcional. Billing y cambio de contraseña son mejoras planificadas. |

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
- `docs/product/module-design-decisions.md` — Visión objetivo detallada y deudas por módulo (sesión 2026-04-09)
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend con orden de implementación
