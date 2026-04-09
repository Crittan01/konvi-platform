# Current Scope — Estado Real de Implementación

Última actualización: 2026-04-09 (rev. 7 — re-baseline completo)

Este documento registra el estado **real y verificado en el repositorio** del producto hoy.
Distingue explícitamente entre lo implementado, lo parcial y lo pendiente.

> **Fuente de verdad**: código en el repo, no documentación previa ni intenciones.

---

## Stack real vigente (verificado en repo)

### Frontend — `apps/web`

| Elemento | Versión real en repo | Notas |
|----------|---------------------|-------|
| Next.js | **14.1.0** | `apps/web/package.json` — NO es Next.js 15 |
| React | ^18 | — |
| TypeScript | ^5 | — |
| TailwindCSS | ^3.3.0 | Con `postcss.config.js` (fix Render) |
| shadcn/ui components | 5 componentes | En `apps/web/components/ui/` — badge, button, card, input, label |
| `@supabase/ssr` | ^0.10.0 | — |
| `@supabase/supabase-js` | ^2.101.1 | — |
| Patrón routing | App Router | Confirmado por estructura `app/` |
| Server Actions | Sí | Usado en catalog/page.tsx |

> **`packages/ui`**: directorio vacío — sin archivos. Los componentes viven en `apps/web/components/ui/`.

### Backend — servicios Python

| Elemento | Versión real | Notas |
|----------|-------------|-------|
| Python (VM) | **3.9.25** | EOL — usar `Optional[X]`, no `X | None` |
| Python (Render) | Sin `runtime.txt` visible — revisar antes de upgrade | Verificar antes de actualizar |
| FastAPI | 0.128.8 | Todos los servicios |
| Pydantic | 2.12.5 | — |
| google-genai | 1.47.0 | SDK oficial Gemini — no `google-generativeai` |
| supabase-py | 2.28.3 | En Render. VM puede tener 2.10.0 local — alinear con `pip3 install supabase==2.28.3` |
| PyJWT | 2.10.1 | Solo en `services/api` |

> **Python objetivo**: 3.11+ para producción. La VM usa 3.9.25 (EOL). No actualizar sin revisar impacto en Oracle Linux 9.

### Packages — estado real

| Package | Archivos | Estado |
|---------|----------|--------|
| `packages/auth` | `lib/server-client.ts`, `lib/client-browser.ts` | 🟡 Parcial — 2 archivos implementados |
| `packages/db` | `migrations/` (6 archivos SQL) | 🟡 Parcial — migraciones SQL, sin tipos TypeScript |
| `packages/ui` | — | ❌ Vacío — cero archivos |
| `packages/config` | — | ❌ Vacío |
| `packages/shared-types` | — | ❌ Vacío |
| `packages/observability` | — | ❌ Vacío |
| `packages/test-utils` | — | ❌ Vacío |

---

## Resumen ejecutivo de implementación

| Capa | Estado | Notas |
|------|--------|-------|
| Tenant Console | 🟡 Parcial | 3 de 13 módulos funcionales |
| Platform Console | ❌ No existe | Cero rutas, cero layout, cero auth de plataforma |
| Backend services | ✅ 3 servicios live | WhatsApp connector, API Gateway, AI Orchestrator |
| Base de datos | ✅ Live | 6 migraciones aplicadas |
| Deploy Render | 🟡 Parcial | PASOS 1-5 ok, PASO 6+7 pendientes humano |
| Shipping/Courier (Envia) | 📋 Diseñado | No implementado — prerequisito PV-03 |
| MeLi | ❌ No iniciado | Requiere Fase 9 completa primero |

---

## Frontend — rutas reales en repo

```
apps/web/app/
├── page.tsx                         ✅ Landing / redirect a /dashboard o /login
├── layout.tsx                       ✅ Root layout
├── globals.css                      ✅
├── login/
│   └── page.tsx                     ✅ Auth con Supabase SSR
└── dashboard/
    ├── layout.tsx                   ✅ Sidebar (3 ítems: Resumen, Catálogo, Inbox AI)
    ├── page.tsx                     🟡 Dashboard — muestra email + nombre de tenant
    ├── catalog/
    │   └── page.tsx                 🟡 Catálogo — CRUD básico, solo primera variante
    └── inbox/
        └── page.tsx                 ✅ Inbox AI — Realtime, human takeover, hilo visual
```

**Sidebar actual** (verificado en `apps/web/app/dashboard/layout.tsx`):
- Resumen → `/dashboard` ✅
- Catálogo → `/dashboard/catalog` 🟡
- Inbox AI → `/dashboard/inbox` ✅

**No hay links rotos**: los 3 ítems del sidebar tienen página.
**No hay links al sidebar que no existan**: ningún ítem "Coming Soon" falso.

**Componentes UI disponibles** (`apps/web/components/ui/`):
- `badge.tsx`, `button.tsx`, `card.tsx`, `input.tsx`, `label.tsx`

---

## Estado detallado por módulo — Tenant Console

### Dashboard (`/dashboard/page.tsx`)
- **Estado**: 🟡 Parcial (proof-of-concept)
- **Qué hace hoy**: Muestra email del usuario y nombre del tenant
- **Qué falta**: KPIs, métricas, alertas, actividad reciente, accesos rápidos
- **Fase que lo completa**: Fase 11 (métricas) o antes con datos disponibles

### Catálogo (`/dashboard/catalog/page.tsx`)
- **Estado**: 🟡 Parcial (base funcional)
- **Qué hace hoy**: Lista productos + primera variante. Formulario crear producto + variante "Standard".
- **Qué falta**: Editar, soft delete desde UI, variantes múltiples, imágenes, paginación, migrar a services/api
- **Fase que lo completa**: Fase 8

### Inbox AI (`/dashboard/inbox/page.tsx`)
- **Estado**: ✅ Funcional
- **Qué hace hoy**: Lista conversaciones, hilo, Realtime, human takeover
- **Qué falta**: Filtros, búsqueda, notas internas, asignación de agente
- **Nota**: Funcional hoy, pero el ciclo E2E real (WhatsApp → Gemini → respuesta) requiere completar Fase 7

---

## Módulos pendientes de implementar — Tenant Console

| Módulo | Ruta objetivo | Fase | Estado |
|--------|--------------|------|--------|
| Media | `/dashboard/media` | 11 | ❌ No existe |
| Inventario | `/dashboard/inventory` | 11 | ❌ No existe |
| Pedidos | `/dashboard/orders` | 9 | ❌ No existe |
| Contactos | `/dashboard/contacts` | 9 | ❌ No existe |
| Knowledge Base | `/dashboard/knowledge-base` | 11 | ❌ No existe |
| Integraciones | `/dashboard/integrations` | 10 | ❌ No existe |
| Shipping / Courier | `/dashboard/shipping` | 10 | 📋 Diseñado — no existe |
| Métricas | `/dashboard/metrics` | 11 | ❌ No existe |
| Auditoría | `/dashboard/audit` | 11 | ❌ No existe |
| Configuración | `/dashboard/settings` | 9 | ❌ No existe |

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
| `services/connector-mercadolibre` | ❌ Directorio vacío | Sin implementación — depende de Fase 9 primero |
| `services/connector-shopify` | ❌ Directorio vacío | Sin implementación — Fase 13 (futuro) |
| `services/connector-envia` | ❌ No existe | Solo diseño documental — depende de Fase 9 + PV-03 |

### Endpoints activos en `services/api`

| Endpoint | Estado | Notas |
|----------|--------|-------|
| `GET /health` | ✅ | — |
| `GET /api/v1/products` | ✅ | Lista productos del tenant (RBAC incompleto) |
| `GET /api/v1/conversations` | ✅ | Lista conversaciones del tenant |
| `PUT /api/v1/products/{id}` | ❌ No existe | Fase 8 |
| `DELETE /api/v1/products/{id}` | ❌ No existe | Fase 8 |
| `GET/POST /api/v1/products/{id}/variations` | ❌ No existe | Fase 8 |
| `GET/POST /api/v1/orders` | ❌ No existe | Fase 9 |
| `PATCH /api/v1/orders/{id}` | ❌ No existe | Fase 9 |
| `GET/PUT /api/v1/settings` | ❌ No existe | Fase 9 |
| `GET/POST/DELETE /api/v1/team` | ❌ No existe | Fase 9 |
| `GET/POST /api/v1/contacts` | ❌ No existe | Fase 9 |
| `POST /api/v1/shipping/quote` | ❌ No existe | Fase 10 |

---

## Tablas de base de datos — estado real

| Tabla | Estado | Migración |
|-------|--------|-----------|
| `tenants` | ✅ Existe | 20260406181235 |
| `tenant_users` | ✅ Existe | 20260406181235 |
| `products` | ✅ Existe | 20260406181236 |
| `product_variations` | ✅ Existe | 20260406181236 |
| `conversations` | ✅ Existe | 20260406181237 |
| `messages` | ✅ Existe + `processed` | 20260406181237 + 20260407200700 |
| `orders` | ❌ No existe | Fase 9 |
| `order_items` | ❌ No existe | Fase 9 |
| `contacts` | ❌ No existe | Fase 9 |
| `tenant_integrations` | ❌ No existe | Fase 9 (prerequisito de Fase 10) |
| `notification_settings` | ❌ No existe | Fase 9 |
| `shipments` | ❌ No existe | Fase 10 |
| `audit_log` | ❌ No existe | Fase 11 |
| `stock_movements` | ❌ No existe | Fase 11 |
| `kb_documents` | ❌ No existe | Fase 11 |

---

## Bloqueos activos

| Bloqueante | Tipo | Impacto |
|-----------|------|---------|
| Meta Webhook Callback URL no configurado (PASO 6) | Intervención humana | Bloquea E2E WhatsApp completo |
| META_ACCESS_TOKEN temporal ~24h (IH-006) | Intervención humana | Bloquea producción real |
| Test E2E no realizado (PASO 7) | Intervención humana + agente | Bloquea confirmar que el sistema funciona en prod |
| RBAC incompleto en `services/api` (R-09) | Deuda técnica | Bloquea onboarding de tenants reales |
| PV-03 sin validar (modelo auth Envia) | Validación pendiente | Bloquea diseño final de `connector-envia` |
| OQ-P01 sin decidir (arquitectura Platform Console) | Decisión pendiente | Bloquea inicio de Fase 12 |

---

## Stack objetivo (no vigente todavía)

| Elemento | Real hoy | Objetivo |
|----------|----------|----------|
| Next.js | 14.1.0 | 15.x (cuando sea estable para el proyecto) |
| Python | 3.9.25 (EOL) | 3.11+ (antes de Beta) |
| packages/ui | Vacío | Componentes shadcn/ui compartidos entre apps |
| packages/shared-types | Vacío | Tipos TypeScript generados de Supabase |
| packages/config | Vacío | Config ESLint/TS compartida |

> No actualizar versiones automáticamente. Cada upgrade requiere validar impacto en Render y en código existente.

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Módulos con evidencia, dependencias y prioridad
- `docs/product/navigation-map.md` — Rutas reales vs faltantes vs propuestas
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend con BLOQUEs de implementación
- `docs/roadmap/implementation-phases.md` — Fases 1-13 re-baselined
