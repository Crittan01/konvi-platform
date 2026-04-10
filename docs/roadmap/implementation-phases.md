# Fases de Implementación — Commerce Ops Platform

Última actualización: 2026-04-10 (rev. 15 — Fases 1-11 completadas)

---

## Estado global

| Fase | Nombre | Estado | Clasificación |
|------|--------|--------|---------------|
| 1 | Base Monorepo | ✅ Completa | COMPLETADO Y VIGENTE |
| 2 | Auth + RLS | ✅ Completa | COMPLETADO Y VIGENTE |
| 3a | Foundation UI — Auth, Dashboard base, Catálogo base | ✅ Completa | COMPLETADO (scope clarificado) |
| 3b | WhatsApp Connector — Webhook boundary Meta | ✅ Completa | COMPLETADO Y VIGENTE |
| 4 | AI Orchestrator — Gemini + guardrails + polling | ✅ Completa | COMPLETADO Y VIGENTE |
| 5 | Inbox AI — Realtime, Human Takeover | ✅ Completa | COMPLETADO Y VIGENTE |
| 6 | API Gateway base — JWT + CRUD básico | ✅ Completa (RBAC pendiente) | COMPLETADO — RBAC INCOMPLETO (R-09) |
| 7 | Deploy Render + E2E | ✅ Completa | COMPLETADO 2026-04-09 |
| 8 | Catálogo completo + RBAC base | ✅ Completa | COMPLETADO 2026-04-09 |
| 9 | Schema core + Pedidos + Configuración + Equipo | ✅ Completa | COMPLETADO 2026-04-09 |
| 10 | Integraciones — MeLi + Envia/Shipping | ✅ Completa | COMPLETADO 2026-04-09 — MeLi OAuth + Envia Sandbox conectados |
| 11 | Módulos restantes Tenant Console + UI Redesign | ✅ Completa | COMPLETADO 2026-04-09 |
| 12 | Platform Console | ❌ Pendiente | PENDIENTE (prerequisito: OQ-P01 + Fase 9+ completa) |
| 13 | Shopify / Tienda custom | ❌ Futuro | FUTURO |

---

## BLOQUE de implementación vs Fase

El orden de BLOQUEs en `docs/architecture/front-back-separation.md` es el orden granular de implementación.
Las Fases en este documento son la agrupación estratégica de esos BLOQUEs.

| BLOQUE (operativo) | Fase (estratégica) |
|--------------------|--------------------|
| BLOQUE 1 | Fase 8 |
| BLOQUE 2 + 3 | Fase 9 |
| BLOQUE 4 | Fase 10 |
| BLOQUE 5 | Fase 11 |
| BLOQUE 6 | Fase 12 |

---

## HISTORIAL — Fases 1-7 (completadas, preservadas)

---

### Fase 1 — Base Monorepo ✅ COMPLETADO Y VIGENTE

- pnpm workspaces configurado
- Estructura: `apps/`, `services/`, `packages/`, `docs/`, `.agents/`
- `.gitignore` correcto (`.env`, `node_modules/`, `.venv/`, `.next/` excluidos)
- `AGENTS.md` y reglas en `.agents/rules/`

---

### Fase 2 — Auth + RLS ✅ COMPLETADO Y VIGENTE

- Supabase Cloud provisionado: `xmelwnhhphksbpdjmbbp` (us-east-1)
- **6 migraciones SQL aplicadas** (tenants, catálogo, conversaciones, RLS, JWT trigger, messages.processed)
- `middleware.ts` SSR protege rutas `/dashboard`
- `app_current_tenant()` función SQL implementada
- RLS en todas las tablas con `tenant_id`

---

### Fase 3a — Foundation UI ✅ COMPLETADO (scope clarificado)

**Scope correcto**: Esta fase estableció el *mínimo viable* de la UI — no el backoffice completo.

- Login funcional con Supabase Auth (`/login`)
- Dashboard: muestra email + tenant (`/dashboard`)
- Catálogo: CRUD básico con Server Actions (`/dashboard/catalog`)
  - Solo primera variante "Standard" hardcodeada
  - Sin edición ni soft delete desde UI
  - Usa Supabase directo (no `services/api`)
- Sidebar con 3 ítems: Resumen, Catálogo, Inbox AI

> **Clasificación corregida**: Esta fase no es "Backoffice completo" — es la base de la UI.
> Los módulos restantes de la Tenant Console se completan en Fases 8, 9 y 11.

---

### Fase 3b — WhatsApp Connector ✅ COMPLETADO Y VIGENTE

- `connector-whatsapp` recibe webhooks de Meta
- HMAC-SHA256 validada ✅
- Parser de payload WhatsApp ✅
- Persistencia en `conversations` y `messages` ✅
- Tenant resolver por `meta_waba_id` real ✅ (fix 2026-04-07)

---

### Fase 4 — AI Orchestrator ✅ COMPLETADO Y VIGENTE

- `worker.py`: Loop polling (batch 10 msgs, `POLL_INTERVAL_SECONDS` configurable)
- `orchestrator.py`: Context builder (catálogo + historial) + Gemini JSON mode + Pydantic
- `guardrails.py`: confidence ≥ 0.65, texto no-nulo, longitud ≤ 1000 chars, human escalation
- `whatsapp_sender.py`: POST Meta Graph API **v21.0** via httpx async (directo — no pasa por connector)
- `tools/catalog_tool.py`: Query productos activos del tenant
- Modelo activo: `gemini-2.5-flash` (billing habilitado)

---

### Fase 5 — Inbox AI Dashboard ✅ COMPLETADO Y VIGENTE

- Lista de conversaciones por tenant ✅
- Hilo inbound/outbound con bubble UI ✅
- Realtime para mensajes nuevos y cambios en conversaciones ✅
- Botón "Tomar control humano" / "Volver al bot" ✅
- Human takeover actualiza `conversations.status` vía Supabase ✅

---

### Fase 6 — API Gateway ✅ COMPLETADO (RBAC incompleto — Riesgo R-09 activo)

- `services/api` con JWT real (PyJWT + Supabase JWT Secret)
- Endpoints activos: `GET /health`, `GET /api/v1/products`, `GET /api/v1/conversations`
- Autorización por `tenant_id` del JWT de Supabase
- CORS restringido via `ALLOWED_ORIGINS`
- **RBAC (owner/manager/agent) por endpoint: PENDIENTE (R-09)** — bloquea acceso real multi-rol

> Nota: El catálogo en la UI usa Supabase directo, no `services/api`. La API existe pero no es consumida por el frontend hoy. Esto se corrige en Fase 8 (BLOQUE 1).

---

### Fase 7 — Deploy en Render ✅ COMPLETADA — 2026-04-09

**4 servicios en producción:**

| Servicio | URL | Estado |
|----------|-----|--------|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background worker, sin URL pública) | ✅ Live, polling 3s |

**Todo completado ✅:**
- 4 servicios desplegados en Render Free plan
- TailwindCSS fix: `postcss.config.js` + `--include=dev` + clear build cache
- Gemini billing habilitado, modelo `gemini-2.5-flash`
- PASO 6: Meta webhook configurado — Callback URL + Verify Token activos
- IH-006: System User Token permanente (`commerce-ops`) — sin expiración
- PASO 7: E2E confirmado — WhatsApp → Connector → Supabase → Orchestrator → Gemini → respuesta
- Inbox AI: conversaciones visibles — bug de trigger JWT resuelto
- Botón logout + mensaje de error en login agregados

**Lecciones aprendidas:**
- `NEW.id` en trigger de `tenant_users` es la PK de la fila, no el user_id → usar `NEW.user_id`
- Después de cambiar `app_metadata`, el usuario debe hacer logout + login para JWT nuevo
- Render Free: background workers duermen tras inactividad — R-03/R-04 activos

---

## ROADMAP ACTIVO — Fases 8-13

---

### Fase 8 — Catálogo completo + RBAC base ✅ COMPLETADO — 2026-04-09

**BLOQUE 1 — usando solo tablas existentes (sin migraciones nuevas)**

**Objetivo**: Que el Catálogo sea usable en producción con RBAC real.

#### Deuda técnica detectada antes de implementar (2026-04-09)

> ⚠️ **Schema mismatch en `services/api/routers/products.py`** (Riesgo R-19):
> El router fue escrito asumiendo una estructura plana de productos que no coincide con el schema real:
> - Usa `name` → schema tiene `title`
> - Usa `is_active` (bool) → schema tiene `status` (TEXT: 'active'/'inactive')
> - Tiene `price`, `sku`, `stock_quantity` en el modelo Product → en el schema están en `product_variations`
> El frontend del catálogo funciona porque usa Supabase directo (con los campos correctos).
> **Corrección**: incluida en esta Fase 8 antes de exponer el API al frontend.

#### En scope — Fase 8 actual

- ✅ Corregir `services/api/routers/products.py` para alinear con schema real
- ✅ RBAC en API: extraer `role` del JWT, proteger endpoints de escritura
- ✅ Edición de producto desde UI (Server Action + Supabase directo)
- ✅ Soft delete desde UI (`status = 'inactive'`)
- ✅ Mostrar/ocultar acciones según role del usuario

#### Deferred — fuera de scope de Fase 8 (deuda documentada)

| Item | Razón del defer | Fase sugerida |
|------|-----------------|---------------|
| Migrar lecturas del catálogo a `services/api` | Supabase directo + RLS ya funciona; complejidad sin beneficio visible ahora | Fase 11 (cuando se necesite para métricas o acceso externo) |
| Gestión de variantes múltiples (UI) | Requiere diseño de UX no trivial; hoy todos los productos tienen 1 variante "Standard" | Fase 9 o 11 |
| `GET/POST /api/v1/products/{id}/variations` | Bloqueado por defer de UI de variantes | Misma que UI |
| SKU en productos | Campo no existe en schema actual — requiere migración | Fase 9 al crear `ALTER TABLE products ADD COLUMN sku TEXT` |
| Paginación en UI de catálogo | Sin volumen de datos real todavía | Fase 11 |

**Tablas necesarias**: Solo las que ya existen (`products`, `product_variations`, `tenant_users`)

**Resultado esperado**: Un tenant real puede crear, editar y desactivar productos. RBAC enforceado en el API.

---

### Fase 9 — Schema core + Pedidos + Configuración + Equipo ✅ COMPLETADO — 2026-04-09

**BLOQUES 2 + 3 — requiere migraciones nuevas**

**Objetivo**: Habilitar el ciclo completo catálogo → pedido y permitir al tenant autogestionar su equipo.

**Migraciones nuevas requeridas:**
```sql
-- orders, order_items: core del negocio
-- contacts: base de clientes (derivable de conversations.customer_phone)
-- tenant_integrations: prerequisito de Fase 10 (MeLi + Envia)
-- notification_settings: config de alertas por tenant
```

**Frontend:**
- `/dashboard/orders` — listado, detalle, crear pedido manual, cambiar estado
- `/dashboard/settings` — perfil empresa, WABA ID, gestión de equipo, notificaciones
- `/dashboard/contacts` — base de clientes con historial

**Backend (`services/api`):**
- `GET/POST /api/v1/orders` — pedidos
- `PATCH /api/v1/orders/{id}` — cambiar estado
- `GET/PUT /api/v1/settings` — configuración del tenant
- `GET/POST/DELETE /api/v1/team` — gestión de usuarios del equipo (RBAC completo)
- `GET/POST /api/v1/contacts` — contactos

**Resultado esperado**: El tenant puede gestionar pedidos, su equipo y su configuración WABA sin intervención técnica.

> **Nota importante**: MeLi y Envia NO van en esta fase. `tenant_integrations` se crea aquí como prerequisito de Fase 10.

---

### Fase 10 — Integraciones: MeLi + Envia/Shipping ✅ COMPLETADO — 2026-04-09

**BLOQUE 4 — prerequisito: Fase 9 completada + PV-03 validado**

**Completado:**
- ✅ OAuth 2.0 MeLi por tenant — user_id `603780765` conectado, tokens en `tenant_integrations`
- ✅ Envia Sandbox conectado — token guardado en `tenant_integrations`, entorno sandbox
- ✅ UI `/dashboard/integrations` — estado de ambas integraciones, connect/disconnect
- ✅ UI `/dashboard/shipping` — historial de cotizaciones (cotización requiere probar endpoint)
- ✅ IH-007 y IH-008 completados
- ✅ Botón OAuth MeLi construye URL en Server Component (sin intermediario API)


**Objetivo**: Conectar marketplaces y shipping. MeLi y Envia van juntos porque comparten prerequisitos.

**Prerequisitos obligatorios antes de comenzar:**
1. `tenant_integrations` tabla existente (Fase 9)
2. `orders` tabla existente (Fase 9)
3. PV-03 validado: ¿cuenta Envia global o por tenant? (ver `docs/research/pending-validations.md`)
4. PV-06 validado: OAuth scopes de MeLi

**MeLi (`services/connector-mercadolibre`):**
- OAuth 2.0 por tenant → credenciales en `tenant_integrations`
- Sync de catálogo ML → `products` + `product_variations`
- Pedidos via IPN webhooks → `orders` + `order_items`
- Actualización de stock bidireccional

**Envia (`services/connector-envia`):**
- Shipping API: quotes (rates), labels, tracking, pickups
- Queries API: carriers, services, country/state, pickup options
- Tabla nueva: `shipments` (migración en esta fase)
- Ver diseño completo: `docs/integrations/courier-envia.md`

**Frontend:**
- `/dashboard/integrations` — conectar/desconectar MeLi y Envia, estado de sync
- `/dashboard/shipping` — cotizar envío, historial, pickups, tracking

**Sub-fases de Envia:**
1. Inicial: conector + tabla shipments + UI + cotizaciones (rates)
2. Fase 2: labels + pickups
3. Fase 3: tracking + webhooks + manifests

---

### Fase 11 — Módulos restantes de Tenant Console + UI Redesign ✅ COMPLETADO — 2026-04-09

**BLOQUE 5 — prerequisito: Fases 8-9 completadas**

**Objetivo**: Visibilidad operacional completa para el tenant + rediseño visual completo.

**Migraciones aplicadas:**
- `20260409240000_stock_movements.sql` — tabla `stock_movements` con delta, new_stock, reason, created_by, RLS
- `20260409250000_kb_documents.sql` — tabla `kb_documents` con is_active, category, updated_at trigger, RLS
- `20260409260000_audit_log.sql` — tabla `audit_log` con action, entity_type, entity_id, payload JSONB, user_email

**Frontend + Backend completados:**
- ✅ `/dashboard/metrics` — 4 KPIs + pedidos por estado + top 5 productos por cantidad/revenue
- ✅ `/dashboard/inventory` — stock por variación + alertas stock bajo (≤5) + ajuste de stock
- ✅ `/dashboard/knowledge-base` — CRUD con Server Actions, categorías, toggle active/inactive
- ✅ `/dashboard/audit` — filtro por entity_type, paginación 25/página, payload expandible
- ✅ `/dashboard/media` — upload/delete/copy URL con Supabase Storage bucket `tenant-media`
- ✅ `services/api/routers/meli_webhook.py` — fire-and-forget 200, BackgroundTask, resolución por `meli_user_id`
- ✅ `services/ai-orchestrator/tools/kb_tool.py` — KB inyectada en system prompt como secciones markdown

**UI Redesign — Dark Warm Theme:**
- ✅ `apps/web/app/globals.css` — paleta "carbón cálido con tinte verde": background `#181E1D`, primary `#38A875`, foreground `#F0EDE8`, amber `#D4A843`
- ✅ `apps/web/app/dashboard/layout.tsx` — sidebar con RBAC visual (NAV_ITEMS[].roles), role badges amber/manager/agent
- ✅ `apps/web/app/layout.tsx` — `next/font/google` Inter con CSS variable `--font-inter` (fix `@import` error PostCSS)
- ✅ `apps/web/tailwind.config.ts` — `fontFamily.sans = ['var(--font-inter)', ...]`

**Nota sobre pgvector / RAG**: Diferido — implementación actual usa inyección de texto plano (markdown) en system prompt, sin embeddings. Funcional y suficiente para el volumen actual. PV-04 sigue abierto para validar disponibilidad en plan Supabase.

---

### Fase 12 — Platform Console ❌ PENDIENTE

**BLOQUE 6 — prerequisito absoluto: OQ-P01 decidido + platform_users + Fase 9+ completa**

**Objetivo**: Herramientas internas para que el dueño de la plataforma opere el SaaS.

**Prerequisitos bloqueantes:**
1. **OQ-P01 decidido**: ¿Misma app Next.js (`/platform/*`) vs app separada (`apps/platform/`) vs subdominio?
2. **Tabla `platform_users`** (o mecanismo equivalente) con roles `platform_superadmin`, `platform_support`, `platform_ops`
3. **Lógica de auth diferenciada** en `middleware.ts` para rutas `/platform/*`
4. **Endpoints platform-only** en `services/api` con validación de rol de plataforma

**Módulos:**
- `/platform` — Overview Global
- `/platform/tenants` + `/platform/tenants/[id]` — Tenants + Tenant Detail
- `/platform/health` — Health Center
- `/platform/integrations` — Integraciones Globales
- `/platform/jobs` — Jobs / Queue Ops
- `/platform/security` — Seguridad
- `/platform/audit` — Auditoría Global
- `/platform/billing` — Billing / Planes
- `/platform/flags` — Feature Flags
- `/platform/support` — Soporte Operativo

Ver `docs/product/personas-and-consoles.md` y `docs/architecture/front-back-separation.md` sección B.

---

### Fase 13 — Shopify / Tienda Custom ❌ FUTURO

- `services/connector-shopify/`
- Integración con Shopify Storefront y Admin API
- Sin fecha definida. Prerequisito: Fases 10-11 completadas.

---

## Regla de actualización

Actualizar este archivo cada vez que:
- Una fase cambia de estado
- Se decide mover algo de fase (documentar por qué)
- Se descubre una nueva dependencia entre fases
- Se completa un BLOQUE de `front-back-separation.md`
