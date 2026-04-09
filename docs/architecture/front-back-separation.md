# Separación Frontend ↔ Backend — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 7 — re-baseline; BLOQUEs alineados con nueva estructura de Fases)

Este documento mapea cada módulo visual con el backend que lo sustenta.
Distingue entre lo que **ya existe en el repo** y lo que **falta**.
Finaliza con el **orden de implementación recomendado** organizado en BLOQUEs.

---

## Principio de separación

```
apps/web (Next.js 14.1.0)
  ├── Server Components  → Supabase directo (lectura con RLS via JWT)
  ├── Server Actions     → Supabase directo (mutaciones simples, actualmente en catálogo)
  ├── Client Components  → Supabase Realtime SDK (subscriptions de inbox)
  └── API calls          → services/api (operaciones transaccionales, RBAC completo)

services/api (FastAPI)
  └── JWT Supabase validado, RBAC por endpoint (RBAC incompleto hoy — R-09)

services/connector-whatsapp (FastAPI)
  └── Boundary con Meta — fire-and-forget, persiste en DB, solo mensajes ENTRANTES

services/ai-orchestrator (FastAPI + worker thread)
  └── Polling loop → Gemini → Meta Graph API v21.0 DIRECTAMENTE (whatsapp_sender.py)
  └── NO pasa por connector-whatsapp para enviar — el conector solo recibe

services/connector-mercadolibre (vacío — Fase 10, tras Fase 9)
services/connector-envia (no existe — Fase 10, tras Fase 9 + validar PV-03)
```

---

## A. TENANT CONSOLE — Mapeo real por módulo

---

### A.1 Dashboard

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Email del usuario | ✅ Existe | `supabase.auth.getUser()` en `dashboard/page.tsx` |
| Nombre del tenant | ✅ Existe | Join `tenant_users → tenants` en `dashboard/page.tsx` |
| KPIs / métricas resumen | ❌ No existe | Ningún archivo — requiere queries de agregación |
| Alertas operacionales | ❌ No existe | Ningún archivo |

**Backend existente**: Solo Supabase directo (lectura de `tenant_users` + `tenants`).
**Backend faltante**: Endpoint de métricas en `services/api`. Tabla `orders` (para métricas de ventas).
**Fase**: 11 (parcialmente antes con datos disponibles de mensajes/conversaciones).

---

### A.2 Inbox / Conversaciones

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Lista de conversaciones | ✅ Existe | Query directa a `conversations` en `inbox/page.tsx` |
| Hilo de mensajes | ✅ Existe | Query a `messages` filtrada por `conversation_id` |
| Realtime mensajes nuevos | ✅ Existe | `supabase.channel` en `inbox/page.tsx` |
| Realtime conversaciones | ✅ Existe | `supabase.channel` en `inbox/page.tsx` |
| Human takeover | ✅ Existe | `UPDATE conversations SET status` |
| Volver al bot | ✅ Existe | `UPDATE conversations SET status = 'bot_active'` |
| Filtros por estado | ❌ No existe | — |
| Búsqueda por teléfono | ❌ No existe | — |
| Asignación de agente | ❌ No existe | Requiere RBAC en `services/api` |

**Backend existente**: Supabase directo para todo lo que funciona.
**Backend faltante**: Filtros/búsqueda en `services/api`. RBAC para asignación.
**Sin dependencias bloqueantes** para la versión actual.

---

### A.3 Catálogo

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Listar productos (con primera variante) | ✅ Existe | `catalog/page.tsx` — query con variantes |
| Crear producto + variante única | ✅ Existe | Server Action en `catalog/page.tsx` |
| Editar producto | ❌ No existe | Sin formulario de edición |
| Eliminar / soft delete | ❌ No existe | Lógica `is_active` en DB pero sin botón en UI |
| Variantes múltiples | ❌ No existe | Solo crea una variante "Standard" hardcodeada |
| Imágenes de producto | ❌ No existe | Sin Supabase Storage configurado |
| Sincronización con MeLi | ❌ No existe | `services/connector-mercadolibre` vacío |
| Paginación | ❌ No existe | — |
| Migración a services/api | ❌ Pendiente | Catálogo usa Supabase directo — `GET /api/v1/products` existe pero no se consume |

**Backend existente**: Supabase directo. `GET /api/v1/products` en `services/api` (existe pero no usado en frontend hoy).
**Backend faltante**: Endpoints `PUT/DELETE/variantes` en `services/api`. Supabase Storage. Connector MeLi.
**Fase**: 8.

---

### A.4 Media

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Subir archivo | ❌ No existe | Supabase Storage — buckets por tenant (sin configurar) |
| Listar media | ❌ No existe | Supabase Storage API |
| Asociar a producto | ❌ No existe | Campo `image_url` o tabla relacional en productos |

**Fase**: 11.

---

### A.5 Inventario

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Ver stock por variante | ❌ No existe como UI | `product_variations.stock_quantity` existe en DB |
| Actualizar stock | ❌ No existe | Endpoint `PUT /api/v1/products/{id}/variations/{vid}` — no creado |
| Historial de movimientos | ❌ No existe | Tabla `stock_movements` no creada |

**Fase**: 11.

---

### A.6 Pedidos

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Listar pedidos | ❌ No existe | Tabla `orders` no creada |
| Detalle de pedido | ❌ No existe | Tabla `order_items` no creada |
| Crear pedido manual | ❌ No existe | Endpoint POST en `services/api` |
| Pedidos desde MeLi | ❌ No existe | `services/connector-mercadolibre` vacío |
| Cambiar estado | ❌ No existe | Endpoint PATCH en `services/api` |

**Dependencia bloqueante**: Shipping, Métricas e Integraciones dependen de esta tabla.
**Fase**: 9.

---

### A.7 Contactos

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Listar contactos | ❌ No existe | Tabla `contacts` no creada |
| Perfil de contacto | ❌ No existe | Join `contacts + conversations + orders` |
| Crear/editar | ❌ No existe | Endpoint en `services/api` |

**Fase**: 9 (derivable de `conversations.customer_phone` inicialmente).

---

### A.8 Knowledge Base

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| CRUD de documentos | ❌ No existe | Tabla `kb_documents` no creada |
| Embeddings | ❌ No existe | Pipeline RAG / pgvector no configurado |
| Integración con orchestrator | ❌ No existe | `tools/kb_tool.py` no creado |

**Prerequisito**: Validar PV-04 (pgvector en Supabase Free).
**Fase**: 11.

---

### A.9 Integraciones

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Conectar cuenta MeLi | ❌ No existe | OAuth MeLi por tenant. Tabla `tenant_integrations` no creada |
| Conectar Envia | ❌ No existe | Config API Key Envia. Tabla `tenant_integrations` no creada |
| Estado de sincronización | ❌ No existe | — |

**Prerequisito**: Tabla `tenant_integrations` (Fase 9) antes de conectar cualquier integración.
**Fase**: 10.

---

### A.10 Shipping / Courier

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Formulario de cotización | 📋 Diseñado | `services/connector-envia` no existe |
| Opciones de carrier | 📋 Diseñado | Envia Shipping API (rates) + Queries API |
| Historial de cotizaciones | 📋 Diseñado | Tabla `shipments` no creada |
| Pickup | 📋 Diseñado | Envia Pickups API |
| Tracking | 📋 Diseñado | Envia Tracking API |

**Prerequisitos bloqueantes**: Tabla `orders` (Fase 9), `services/connector-envia` (Fase 10), PV-03 validado.
**Fase**: 10 (junto con MeLi, después de Fase 9).

---

### A.11 Métricas

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Mensajes por día | ❌ No existe | Query GROUP BY sobre `messages` (tabla existe) |
| Conversaciones activas | ❌ No existe | Query sobre `conversations.status` (tabla existe) |
| Pedidos / conversiones | ❌ No existe | Tabla `orders` no creada |

**Fase**: 11 (mensajes/conversaciones pueden hacerse antes; pedidos requieren Fase 9).

---

### A.12 Auditoría

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Log de acciones | ❌ No existe | Tabla `audit_log` no creada |
| Filtros | ❌ No existe | — |

**Fase**: 11.

---

### A.13 Configuración

| Aspecto | Estado | Backend requerido |
|---------|--------|-------------------|
| Editar WABA ID | ❌ No existe | Endpoint PUT en `services/api` |
| Gestión de equipo (RBAC) | ❌ No existe | Endpoints RBAC en `services/api` (incompleto — R-09) |
| Notificaciones | ❌ No existe | Tabla `notification_settings` no creada |

**Fase**: 9.

---

## B. PLATFORM CONSOLE

Toda la Platform Console requiere backend que no existe.

### Prerrequisito bloqueante — Auth y roles de plataforma

**Antes de construir cualquier módulo de Platform Console**, se requiere:

1. **Tabla `platform_users`** (o mecanismo equivalente) — no existe en DB
   - Roles: `platform_superadmin`, `platform_support`, `platform_ops`
   - Separada de `tenant_users` — no compartir roles
2. **Lógica de autenticación diferenciada** en `middleware.ts`
   - `/platform/*` debe verificar rol de plataforma (no tenant)
   - Hoy: solo protege `/dashboard/*` con rol de tenant
3. **Endpoint platform-only** en `services/api` con validación de rol de plataforma

> Sin este prerrequisito, **ningún módulo de Platform Console puede construirse con seguridad**.

### Decisión arquitectónica pendiente (OQ-P01)

¿La Platform Console es parte de la misma app Next.js o una app separada?
- a) **Misma app** (`/platform/*` con layout separado) — más simple, ya usado para `/dashboard/*`
- b) **App separada** (`apps/platform/`) — más limpia, más overhead
- c) **Sub-dominio** (`platform.commerce-ops.com`) — mayor separación física

**Recomendación provisional**: opción (a) por simplicidad. **Validar antes de implementar.**

### Backend mínimo por módulo de Platform Console

| Módulo | Backend mínimo requerido | Fase |
|--------|--------------------------|------|
| Overview Global | `platform_users` + Queries cross-tenant con `service_role` | 12 |
| Tenants | `platform_users` + Endpoints platform-admin en `services/api` | 12 |
| Health Center | Endpoints `/health` de cada servicio (parcialmente existen) + agregador | 12 |
| Jobs / Queue Ops | Endpoint `/status` del orchestrator (existe) + métricas en `services/api` | 12 |
| Seguridad | `platform_users` + `platform_audit_log` | 12 |
| Auditoría Global | Tabla `audit_log` (no existe — necesaria también en A.12) + extensión con `actor_type = platform` | 12 |
| Billing/Planes | Tabla `tenant_plans` (no existe) — posiblemente Stripe | 12 |
| Feature Flags | Tabla `feature_flags` (no existe) | 12 |
| Soporte Operativo | `platform_users` + acceso auditado cross-tenant | 12 |

**Prerrequisito de orden**: Fases 8-11 (Tenant Console con módulos core completos) antes de Platform Console.

---

## Servicios backend — estado real

| Servicio | Existe | Live | Endpoints activos |
|----------|--------|------|-------------------|
| `services/api` | ✅ | ✅ Render | `GET /health`, `GET /api/v1/products`, `GET /api/v1/conversations` |
| `services/connector-whatsapp` | ✅ | ✅ Render | `GET/POST /api/v1/whatsapp/webhook` |
| `services/ai-orchestrator` | ✅ | ✅ Render | `GET /health`, `GET /status` + worker interno |
| `services/connector-mercadolibre` | ✅ directorio | ❌ vacío | Ninguno — Fase 10 |
| `services/connector-shopify` | ✅ directorio | ❌ vacío | Ninguno — Fase 13 |
| `services/connector-envia` | ❌ no existe | ❌ | No existe — Fase 10 + PV-03 |

### Endpoints faltantes en `services/api` (por fase y prioridad)

| Endpoint | Módulo | Fase | Prioridad |
|----------|--------|------|-----------|
| `PUT /api/v1/products/{id}` | Catálogo — editar | 8 | Alta |
| `DELETE /api/v1/products/{id}` | Catálogo — soft delete | 8 | Alta |
| `GET/POST /api/v1/products/{id}/variations` | Catálogo — variantes | 8 | Alta |
| `GET/POST /api/v1/orders` | Pedidos | 9 | Alta |
| `PATCH /api/v1/orders/{id}` | Pedidos — cambiar estado | 9 | Alta |
| `GET/PUT /api/v1/settings` | Configuración | 9 | Alta |
| `GET/POST/DELETE /api/v1/team` | Configuración — equipo | 9 | Alta |
| `GET/POST /api/v1/contacts` | Contactos | 9 | Media |
| `POST /api/v1/shipping/quote` | Shipping — cotizar | 10 | Media |
| `GET /api/v1/metrics` | Métricas | 11 | Media |
| `GET /api/v1/audit` | Auditoría | 11 | Media |

---

## Tablas pendientes de crear (por fase y prioridad)

| Tabla | Módulo dependiente | Fase | Prioridad |
|-------|--------------------|------|-----------|
| `orders` | Pedidos, Shipping, Métricas, MeLi | 9 | Alta |
| `order_items` | Pedidos | 9 | Alta |
| `tenant_integrations` | Integraciones (MeLi, Envia) — prerequisito Fase 10 | 9 | Alta |
| `notification_settings` | Configuración | 9 | Media |
| `contacts` | Contactos | 9 | Media |
| `shipments` | Shipping / Courier | 10 | Media |
| `audit_log` | Auditoría Tenant + Platform | 11 | Media |
| `stock_movements` | Inventario | 11 | Media |
| `kb_documents` | Knowledge Base | 11 | Baja |

---

## Orden de implementación — BLOQUEs (granular) y Fases (estratégicas)

### PRERREQUISITO ACTUAL (bloqueante humano)

Completar Fase 7 PASO 6 + 7 y IH-006 (Meta Webhook + System User Token + E2E test).
No tiene sentido seguir hasta confirmar que el ciclo WhatsApp→Gemini funciona en producción.

---

### BLOQUE 1 → Fase 8: Catálogo completo + RBAC base

> Objetivo: Catálogo usable en producción con control de acceso real.
> **Sin migraciones nuevas** — usa tablas existentes.

1. Agregar edición de producto en UI (Server Action o `PUT /api/v1/products/{id}`)
2. Agregar soft delete en UI (UPDATE `is_active=false`)
3. Agregar gestión de variantes múltiples (formulario + endpoints)
4. Migrar lectura de catálogo a `services/api` (en vez de Supabase directo)
5. Implementar RBAC básico en `services/api` (owner puede crear/editar, agent solo lee)

---

### BLOQUE 2 → Fase 9 (primera mitad): Schema core + Pedidos

> Objetivo: Ciclo catálogo → pedido funcional.

1. Crear migraciones: `orders` + `order_items` + `tenant_integrations` + `contacts` + `notification_settings`
2. Implementar endpoints CRUD en `services/api` para orders
3. Implementar UI `/dashboard/orders`
4. Vincular pedido con conversación desde el Inbox
5. Crear endpoint y UI básica de `/dashboard/contacts`

---

### BLOQUE 3 → Fase 9 (segunda mitad): Configuración + equipo

> Objetivo: Tenant puede gestionar su equipo sin intervención técnica.

1. Implementar endpoints RBAC (invite, change role, remove) en `services/api`
2. Implementar UI `/dashboard/settings` (WABA, equipo, notificaciones, plan)
3. RBAC completo en todos los endpoints existentes

---

### BLOQUE 4 → Fase 10: Integraciones (MeLi + Envia juntos)

> Objetivo: Conectar MeLi y Envia. Van juntos porque comparten prerequisitos.
> **Prerequisito**: `tenant_integrations` + `orders` de Fases 9. PV-03 y PV-06 validados.

1. Implementar OAuth MeLi por tenant → credenciales en `tenant_integrations`
2. Crear `services/connector-mercadolibre` (sync catálogo + orders via IPN)
3. Validar PV-03 (modelo auth Envia) → diseño final de `connector-envia`
4. Crear migración: `shipments`
5. Implementar `services/connector-envia` (Shipping API + Queries API)
6. Implementar UI `/dashboard/integrations`
7. Implementar UI `/dashboard/shipping`

---

### BLOQUE 5 → Fase 11: Módulos restantes Tenant Console

> Objetivo: Visibilidad operacional completa para el tenant.

1. Crear migraciones: `audit_log`, `stock_movements`, `kb_documents`
2. Implementar log de auditoría en `services/api` para todas las mutaciones
3. Implementar UI `/dashboard/audit`
4. Implementar UI `/dashboard/inventory`
5. Implementar UI `/dashboard/metrics`
6. Implementar Supabase Storage + UI `/dashboard/media`
7. Implementar pipeline RAG + UI `/dashboard/knowledge-base` (post PV-04)

---

### BLOQUE 6 → Fase 12: Platform Console

> Objetivo: Herramientas internas para operar el SaaS.
> **Prerequisito absoluto**: OQ-P01 decidido + `platform_users` + Fases 8-11 completadas.

1. Decidir OQ-P01 (misma app `/platform/*` vs app separada)
2. Crear tabla `platform_users` con roles de plataforma
3. Actualizar `middleware.ts` para separar auth de `/platform/*` vs `/dashboard/*`
4. Implementar layout de Platform Console
5. Implementar módulos según prioridad: Overview → Tenants → Health → Jobs → Auditoría

---

## Resumen visual del orden

```
HOY (humano)  → Fase 7 PASO 6 + IH-006 + PASO 7 (E2E)
BLOQUE 1      → Fase 8:  Catálogo completo + RBAC base
BLOQUE 2+3    → Fase 9:  Schema core + Pedidos + Contactos + Configuración + Equipo
BLOQUE 4      → Fase 10: MeLi + Envia (validar PV-03 y PV-06 antes)
BLOQUE 5      → Fase 11: Auditoría + Inventario + Métricas + Media + KB
BLOQUE 6      → Fase 12: Platform Console (OQ-P01 antes)
```

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Estado por módulo con evidencia
- `docs/product/navigation-map.md` — Rutas reales vs faltantes
- `docs/data/schema.md` — Tablas vigentes y pendientes
- `docs/architecture/modules.md` — Estado de servicios backend
- `docs/roadmap/implementation-phases.md` — Fases re-baselined (rev. 7)
