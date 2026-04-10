# Separación Frontend ↔ Backend — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 8 — BLOQUEs 1-5 completados; estados actualizados post Fases 8-11)

Este documento mapea cada módulo visual con el backend que lo sustenta.
Distingue entre lo que **ya existe en el repo** y lo que **falta**.
Finaliza con el **orden de implementación recomendado** organizado en BLOQUEs.

---

## Principio de separación

```
apps/web (Next.js 14.2.35)
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

services/connector-mercadolibre (vacío — conector MeLi implementado en services/api/integrations/meli_client.py)
services/connector-envia (no existe — cliente Envia en services/api/integrations/envia_client.py)
```

---

## A. TENANT CONSOLE — Mapeo real por módulo

---

### A.1 Dashboard

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Email del usuario | ✅ Existe | `supabase.auth.getUser()` en `dashboard/page.tsx` |
| Nombre del tenant | ✅ Existe | Join `tenant_users → tenants` en `dashboard/page.tsx` |
| KPIs / métricas resumen | ✅ Existe | Tabs Operaciones/Negocio — pedidos, conversaciones, contactos, mensajes |
| Alertas operacionales | ❌ Pendiente | Deuda futura |

**Backend existente**: Supabase directo + queries paralelas con `Promise.all`.
**Fase completada**: 11.

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
| Editar producto | ✅ Existe | Server Action + PUT en `services/api` (Fase 8) |
| Eliminar / soft delete | ✅ Existe | status = 'inactive' (Fase 8) |
| Variantes múltiples | ❌ Pendiente | Solo crea una variante "Standard" — deuda técnica |
| Imágenes de producto | ❌ Pendiente | Supabase Storage existe (Media A.4) pero no vinculado a productos |
| Sincronización con MeLi | ❌ Pendiente | OAuth MeLi conectado. Sync catálogo: deuda futura |
| Paginación | ❌ Pendiente | Sin volumen real todavía |

**Backend existente**: `products.py` router con CRUD completo. RBAC enforceado (owner/manager).
**Backend pendiente**: Variantes múltiples, paginación, sync MeLi.
**Fase completada**: 8. Deuda técnica en módulo.

---

### A.4 Media

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Subir archivo | ✅ Existe | Supabase Storage bucket `tenant-media` |
| Listar media | ✅ Existe | `supabase.storage.from('tenant-media').list(folder)` |
| Eliminar | ✅ Existe | `supabase.storage.from('tenant-media').remove([path])` |
| Asociar a producto | ❌ Pendiente | Deuda técnica — campo `image_url` no vinculado |

**Fase completada**: 11.

---

### A.5 Inventario

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Ver stock por variante | ✅ Existe | `product_variations.stock_quantity` |
| Ajuste de stock | ✅ Existe | Server Action → inserta en `stock_movements` |
| Alerta stock bajo (≤5) | ✅ Existe | Condicional en UI |
| Historial de movimientos | 🟡 Parcial | `stock_movements` existe pero sin UI paginada |

**Fase completada**: 11.

---

### A.6 Pedidos

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Listar pedidos | ✅ Existe | `orders.py` + `orders` tabla |
| Detalle de pedido | ✅ Existe | `order_items` tabla |
| Crear pedido manual (UI) | ❌ Pendiente | Endpoint existe — formulario en UI pendiente |
| Pedidos desde MeLi | 🟡 Parcial | `meli_webhook.py` procesa notificaciones `orders_v2` |
| Cambiar estado | ✅ Existe | `PATCH /api/v1/orders/{id}` |

**Fase completada**: 9. Crear pedido manual desde UI es deuda menor.

---

### A.7 Contactos

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Listar contactos | ✅ Existe | `contacts.py` + `contacts` tabla |
| Perfil de contacto | ✅ Existe | Vista individual |
| Historial cruzado (pedidos + convs) | ❌ Pendiente | Join no implementado en UI |

**Fase completada**: 9. Historial cruzado es mejora futura.

---

### A.8 Knowledge Base

| Aspecto | Estado | Backend |
|---------|--------|---------|
| CRUD de documentos | ✅ Existe | Server Actions + `kb_documents` tabla |
| Categorías + toggle activo | ✅ Existe | Categorías: faq/politica/negocio/producto/general |
| Inyección en orchestrator | ✅ Existe | `kb_tool.py` — `asyncio.gather()` con catálogo |
| Embeddings / pgvector RAG | ❌ Pendiente | PV-04 sin validar. Diferido — texto plano es suficiente ahora. |

**Fase completada**: 11. pgvector como deuda técnica (PV-04).

---

### A.9 Integraciones

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Conectar MeLi (OAuth) | ✅ Existe | `meli_client.py` + OAuth callback + `tenant_integrations` |
| Conectar Envia (API key) | ✅ Existe | `envia_client.py` + `integrations.py` router |
| Estado de sincronización | 🟡 Parcial | Status `connected/disconnected` visible — logs de sync pendientes |

**Fase completada**: 10.

---

### A.10 Shipping / Courier

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Historial de envíos | ✅ Existe | `shipping.py` → `GET /api/v1/shipping/history` |
| Cotización (backend) | ✅ Existe | `POST /api/v1/shipping/quote` → Envia `POST /ship/rate/` |
| Formulario UI interactivo | ✅ Existe | `ShippingQuoteForm` — Client Component con selección de carrier |
| Labels | ❌ Pendiente | Fase 2 de Envia |
| Tracking | ❌ Pendiente | Fase 2 de Envia |
| Pickup | ❌ Pendiente | Fase 2 de Envia |

**Fase completada**: 10-11 (Fase Inicial). Fases 2-3 de Envia pendientes (label/tracking/pickup).

---

### A.11 Métricas

| Aspecto | Estado | Backend |
|---------|--------|---------|
| KPIs (mensajes, convs, pedidos, contactos) | ✅ Existe | `Promise.all` sobre Supabase directo |
| Pedidos por estado | ✅ Existe | Query con GROUP BY |
| Top 5 productos | ✅ Existe | Query sobre `order_items` |
| Gráficas de tendencia | ❌ Pendiente | Deuda futura |

**Fase completada**: 11.

---

### A.12 Auditoría

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Log de acciones | ✅ Existe | `audit_log` tabla + escritura explícita desde API |
| Filtro por entity_type | ✅ Existe | Query params en Server Component |
| Paginación | ✅ Existe | 25 items/página |
| Filtro por usuario | ❌ Pendiente | Deuda futura |

**Fase completada**: 11.

---

### A.13 Configuración

| Aspecto | Estado | Backend |
|---------|--------|---------|
| Editar WABA ID | ✅ Existe | `PUT /api/v1/settings` |
| Gestión de equipo | ✅ Existe | `GET/POST/DELETE /api/v1/team` + `get_tenant_team()` SECURITY DEFINER |
| Notificaciones | ✅ Existe | `notification_settings` tabla |
| Billing / planes | ❌ Pendiente | Fase 12 |

**Fase completada**: 9.

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

## Servicios backend — estado real (post Fase 11)

| Servicio | Existe | Live | Routers / funcionalidad |
|----------|--------|------|------------------------|
| `services/api` | ✅ | ✅ Render | 8 routers: products, orders, contacts, settings, integrations, shipping, meli_webhook, conversations |
| `services/connector-whatsapp` | ✅ | ✅ Render | Recibe webhooks Meta, HMAC validado, persiste en DB |
| `services/ai-orchestrator` | ✅ | ✅ Render | Polling, Gemini, KB + catálogo en prompt, `tools/kb_tool.py` |
| `services/connector-mercadolibre` | ✅ directorio | ❌ vacío | Cliente en `services/api/integrations/meli_client.py` |
| `services/connector-shopify` | ✅ directorio | ❌ vacío | Ninguno — Fase 13 |

### Endpoints activos en `services/api` (Fases 1-11)

| Endpoint | Estado |
|----------|--------|
| `GET /health` | ✅ |
| `GET/POST /api/v1/products` | ✅ |
| `PUT/DELETE /api/v1/products/{id}` | ✅ |
| `GET /api/v1/conversations` | ✅ |
| `GET/POST /api/v1/orders` | ✅ |
| `PATCH /api/v1/orders/{id}` | ✅ |
| `GET/POST /api/v1/contacts` | ✅ |
| `GET/PUT /api/v1/settings` | ✅ |
| `GET/POST/DELETE /api/v1/team` | ✅ |
| `POST /api/v1/integrations/envia` | ✅ |
| `DELETE /api/v1/integrations/envia` | ✅ |
| `GET/POST /api/v1/integrations/meli` | ✅ |
| `GET /api/v1/integrations/meli/callback` | ✅ |
| `POST /api/v1/shipping/quote` | ✅ |
| `GET /api/v1/shipping/history` | ✅ |
| `POST /api/v1/meli/webhook` | ✅ |

### Endpoints pendientes (próximas fases)

| Endpoint | Módulo | Fase |
|----------|--------|------|
| `POST /api/v1/shipping/label` | Envia Fase 2 | 12 deuda |
| `GET /api/v1/shipping/tracking/{id}` | Envia Fase 2 | 12 deuda |
| `POST /api/v1/shipping/pickup` | Envia Fase 2 | 12 deuda |
| Endpoints platform-only | Platform Console | 12 |

---

## Tablas — estado real (13 migraciones aplicadas, todas en `supabase/migrations/`)

| Tabla | Migración | Estado |
|-------|-----------|--------|
| `tenants`, `tenant_users` | 20260406181235 | ✅ |
| `products`, `product_variations` | 20260406181236 | ✅ |
| `conversations`, `messages` | 20260406181237 + 20260407200700 | ✅ |
| `contacts`, `orders`, `order_items`, `tenant_integrations`, `notification_settings` | 20260409220000 | ✅ |
| `shipments` | 20260409230000 | ✅ |
| `stock_movements` | 20260409240000 | ✅ |
| `kb_documents` | 20260409250000 | ✅ |
| `audit_log` | 20260409260000 | ✅ |
| `platform_users` | — | ❌ Fase 12 |

---

## Orden de implementación — BLOQUEs (granular) y Fases (estratégicas)

### BLOQUEs 1-5 COMPLETADOS (2026-04-09)

| BLOQUE | Fase | Estado |
|--------|------|--------|
| BLOQUE 1 | Fase 8: Catálogo + RBAC | ✅ Completado |
| BLOQUE 2+3 | Fase 9: Schema core + Pedidos + Config | ✅ Completado |
| BLOQUE 4 | Fase 10: MeLi + Envia | ✅ Completado (Fase Inicial) |
| BLOQUE 5 | Fase 11: Módulos restantes TC + UI Redesign | ✅ Completado |

---

### BLOQUE 6 → Fase 12: Platform Console ❌ PENDIENTE

> Objetivo: Herramientas internas para operar el SaaS.
> **Prerequisito absoluto**: OQ-P01 decidido + `platform_users` + Fases 8-11 completadas ✅.

1. Decidir OQ-P01 (misma app `/platform/*` vs app separada) — **BLOQUEANTE**
2. Crear tabla `platform_users` con roles de plataforma
3. Actualizar `middleware.ts` para separar auth de `/platform/*` vs `/dashboard/*`
4. Implementar layout de Platform Console
5. Implementar módulos según prioridad: Overview → Tenants → Health → Jobs → Auditoría

---

### Deuda técnica pendiente (pre-Fase 12)

Antes de iniciar Fase 12, se recomienda cerrar:

| Deuda | Módulo | Prioridad |
|-------|--------|-----------|
| Variantes múltiples en catálogo | Catálogo | Media |
| Label + tracking + pickup Envia | Shipping Fase 2 | Media |
| Sincronizar `packages/db/migrations/` con `supabase/migrations/` | DB | Media |
| RBAC granular completo por endpoint (R-09) | API Gateway | Media |

---

## Resumen visual del orden

```
BLOQUE 1      → Fase 8:  ✅ Catálogo completo + RBAC base
BLOQUE 2+3    → Fase 9:  ✅ Schema core + Pedidos + Contactos + Configuración + Equipo
BLOQUE 4      → Fase 10: ✅ MeLi OAuth + Envia Fase Inicial
BLOQUE 5      → Fase 11: ✅ Auditoría + Inventario + Métricas + Media + KB + UI Redesign
BLOQUE 6      → Fase 12: ❌ Platform Console (OQ-P01 antes)
```

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Estado por módulo con evidencia
- `docs/product/navigation-map.md` — Rutas reales vs faltantes
- `docs/data/schema.md` — Tablas vigentes y pendientes
- `docs/architecture/modules.md` — Estado de servicios backend
- `docs/roadmap/implementation-phases.md` — Fases 1-11 completadas, 12-13 pendientes
