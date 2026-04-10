# Handoff — Estado del Proyecto al 2026-04-10 (rev. 14)

Este documento existe para que el próximo chat de IA retome trabajo exactamente desde donde se dejó.
**Leer este archivo antes de cualquier otra acción.**

---

## Resumen del sistema

**Commerce Ops Platform** — SaaS multi-tenant de operaciones e-commerce conversacionales.

- Canal principal: WhatsApp Cloud API (Meta oficial v21.0)
- Tenants aislados con RLS en PostgreSQL (Supabase)
- IA: Google Gemini via `google-genai==1.47.0` (modelo: `gemini-2.5-flash`)
- Hosting: Render.com (4 servicios live en Free plan)
- El producto NO es un bot — es una plataforma de operaciones donde el LLM es una capa de asistencia

### Stack real en repo (verificado en package.json / requirements.txt)
- Frontend: **Next.js 14.1.0** (no 15), React ^18, TailwindCSS ^3.3.0
- 5 componentes shadcn/ui en `apps/web/components/ui/` — `packages/ui` está vacío
- Python **3.9.25** en VM (EOL) — requirements.txt especifica FastAPI 0.128.8, google-genai 1.47.0

---

## Fases completadas (no tocar)

| Fase | Descripción | Archivos clave |
|------|-------------|----------------|
| 1 | Base monorepo pnpm | `pnpm-workspace.yaml`, `.gitignore` |
| 2 | Auth + RLS Supabase | `supabase/migrations/` (6 migraciones) |
| 3a | Backoffice Next.js | `apps/web/app/dashboard/` |
| 3b | WhatsApp Connector | `services/connector-whatsapp/` |
| 4 | AI Orchestrator | `services/ai-orchestrator/` |
| 5 | Inbox AI (Realtime) | `apps/web/app/dashboard/inbox/page.tsx` |
| 6 | API Gateway real | `services/api/` (JWT real, CRUD completo) |
| 7 | Deploy Render + E2E confirmado | 4 servicios live, WhatsApp ↔ Gemini ↔ Inbox ✅ |
| 8 | Catálogo completo + RBAC base | `services/api/routers/products.py`, `apps/web/app/dashboard/catalog/` |
| 9 | Schema core + Pedidos + Config + Equipo | `supabase/migrations/20260409220000_fase9_schema_core.sql`, routers orders/contacts/settings |
| 10 | Integraciones MeLi + Envia | `services/api/integrations/`, `apps/web/app/dashboard/integrations/`, `apps/web/app/dashboard/shipping/` |
| 11 | Módulos Tenant Console + UI Redesign | `apps/web/app/dashboard/{metrics,inventory,knowledge-base,audit,media}/`, `services/api/routers/meli_webhook.py`, `services/ai-orchestrator/tools/kb_tool.py`, `apps/web/app/globals.css`, `apps/web/app/dashboard/layout.tsx` |

---

## Estado de Fase 7 — Deploy Render ✅ COMPLETADA

### 4 servicios en producción

| Servicio | URL | Estado |
|----------|-----|--------|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live, UI con TailwindCSS |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background, sin URL pública) | ✅ Live, polling cada 3s |

### Completado (2026-04-09)

- ✅ PASO 6: Meta webhook configurado — Callback URL + Verify Token activos
- ✅ IH-006: System User Token permanente (`commerce-ops`) — sin expiración
- ✅ PASO 7: E2E confirmado — WhatsApp → Connector → Supabase → Orchestrator → Gemini → respuesta enviada
- ✅ Inbox AI: conversaciones visibles en `/dashboard/inbox` tras fix del trigger JWT
- ✅ Botón de logout añadido al sidebar (faltaba pese a que LogOut estaba importado)
- ✅ Mensaje de error en login al fallar autenticación

### Bug crítico resuelto — Trigger JWT (rev. 8)

**Síntoma**: Inbox mostraba 0 conversaciones aunque sí existían en Supabase.

**Causa**: `handle_new_user_claims()` usaba `NEW.id` (PK de `tenant_users`) en vez de `NEW.user_id` (ID del usuario en `auth.users`). Resultado: `app_metadata.tenant_id` nunca se seteaba → RLS filtraba todo.

**Fix 1 — inmediato**: `UPDATE auth.users SET raw_app_meta_data = jsonb_set(...)` para el usuario existente `87da7bb6-...`.

**Fix 2 — permanente**: `CREATE OR REPLACE FUNCTION handle_new_user_claims()` con `NEW.user_id` y `NEW.tenant_id` correctos. Aplicado vía `supabase db query --linked`.

> Para futuros nuevos usuarios: el trigger ahora funciona correctamente. No se requiere acción manual.

---

## Trabajo completado en esta sesión (rev. 7 — 2026-04-09) — RE-BASELINE COMPLETO

Sesión de re-sincronización completa del proyecto desde Fase 1/Paso 1.

### Problema crítico resuelto (rev. 7)

**Dependencia invertida en el roadmap anterior:**
- El roadmap decía: Fase 8 = MeLi, Fase 9 = Tenant Console modules
- MeLi requiere: `orders`, `order_items`, `tenant_integrations` (tablas de Fase 9)
- Era imposible hacer Fase 8 antes que Fase 9
- Consecuencia: el roadmap era incoherente y no se podía seguir linealmente

### Nueva estructura de fases (rev. 7)

| Fase anterior | Fase nueva | Cambio |
|---------------|------------|--------|
| Fase 8: MeLi | → Fase 10: Integraciones (MeLi + Envia juntos) | MeLi ahora después del schema core |
| Fase 9: Todos los módulos TC | → Fase 8: Catálogo + RBAC base | Catálogo primero, sin migraciones |
| — | → Fase 9: Schema core + Pedidos + Config | Schema core que habilita Fase 10 |
| Fase 10: Shipping solo | → Parte de Fase 10: Integraciones | Shipping con MeLi, comparten prerequisitos |
| Fase 11: Platform Console | → Fase 11: Módulos restantes TC | Platform Console espera más |
| Fase 12: Shopify | → Fase 12: Platform Console | Subió un lugar |
| — | → Fase 13: Shopify | Nuevo número |

### Archivos actualizados (rev. 7)

| Archivo | Cambio |
|---------|--------|
| `docs/roadmap/implementation-phases.md` | Re-baseline completo — Fases 1-13 con nueva estructura + nota de re-baseline |
| `docs/roadmap/milestones.md` | Actualizado: Alpha Interno (bloqueante correcto), Beta Controlada (ajuste de timeline), RC ajustado |
| `docs/product/current-scope.md` | Módulos actualizados con nueva asignación de Fases; endpoints faltantes por Fase |
| `docs/architecture/front-back-separation.md` | BLOQUEs alineados con nueva estructura de Fases; tablas y endpoints por Fase |
| `docs/risks/open-questions.md` | OQ-06 añadido; columna "Bloquea" añadida; OQ-P03 con contexto de re-baseline |
| `docs/research/pending-validations.md` | Columna "Bloquea" añadida; PV-03 y PV-06 marcados como críticos para Fase 10 |
| `AGENTS.md` | Rev. 7 — nueva tabla de Fases en sección de contexto documental |

### Contradicciones/errores corregidos (rev. 6 — sesión anterior)

| Archivo | Error | Corrección |
|---------|-------|-----------|
| `README.md` | Completamente desactualizado — Next.js 15, Python 3.11+, 5 migraciones, estados obsoletos | Reescritura completa |
| `docs/architecture/overview.md` | Diagrama incorrecto: orchestrator → connector-whatsapp → Meta API | Corregido: orchestrator → Meta API directo |
| `docs/roadmap/implementation-phases.md` | Shipping en Fase 9 Y Fase 10 (contradicción) | Resuelta (luego re-baselined en rev. 7) |
| `docs/research/official-doc-checklist.md` | "Next.js 15 Docs" — stack real es 14.1.0 | Corregido |
| `docs/architecture/modules.md` | Fecha desfasada 2026-04-08 | Actualizado |

---

## Trabajo completado en sesión anterior (rev. 5 — 2026-04-09)

Se auditó la completitud documental del repositorio y se corrigieron contradicciones encontradas.

### Contradicciones corregidas (rev. 5)

| Archivo | Error | Corrección |
|---------|-------|-----------|
| `docs/architecture/overview.md` | Diagrama decía "Next.js 15" | Corregido a "Next.js 14.1.0" |
| `docs/architecture/modules.md` | Decía "Next.js 15" | Corregido a "Next.js 14.1.0" |
| `docs/architecture/modules.md` | Versiones Python stale: `fastapi==0.115.12`, `uvicorn==0.34.0`, `python-dotenv==1.0.1` | Corregido a versiones reales en requirements.txt |
| `docs/architecture/modules.md` | `SUPABASE_JWT_SECRET` marcado como pendiente | Corregido a ✅ resuelto |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-004 marcado EN PROGRESO | Actualizado: PASOS 1-5 ✅, PASOS 6-7 pendientes humano |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-005 marcado PENDIENTE | Actualizado a ✅ COMPLETADO |

---

## Trabajo completado en sesión anterior (rev. 4)

Se completó una actualización documental completa del repositorio.

### Archivos CREADOS

| Archivo | Propósito |
|---------|-----------|
| `docs/product/current-scope.md` | Estado real de implementación hoy |
| `docs/product/personas-and-consoles.md` | Definición de Tenant Console y Platform Console |
| `docs/product/admin-ui-modules.md` | Módulos detallados de ambas consolas con estado |
| `docs/product/navigation-map.md` | Mapa de navegación objetivo de ambas consolas |
| `docs/architecture/front-back-separation.md` | Mapeo Frontend ↔ Backend por módulo |
| `docs/integrations/courier-envia.md` | Diseño completo del módulo Shipping/Courier (Envia) |

### Archivos ACTUALIZADOS (reescritos)

| Archivo | Qué cambió |
|---------|-----------|
| `docs/product/overview.md` | De 1 línea a doc completo del producto |
| `docs/product/scope.md` | De 1 línea a alcance funcional completo |
| `docs/architecture/overview.md` | Actualizado modelo Gemini, estado servicios, diagrama |
| `docs/architecture/connector-framework.md` | Actualizado WA status, añadido Envia diseñado |
| `docs/integrations/whatsapp.md` | Actualizado (HMAC ok, PASO 6 pendiente, IH-006) |
| `docs/integrations/mercadolibre.md` | De 1 línea a doc completo (Fase 8) |
| `docs/integrations/telegram.md` | De 1 línea a doc completo (canal interno) |
| `docs/data/schema.md` | Expandido con tablas vigentes y pendientes |
| `docs/data/tenant-isolation.md` | De 1 línea a doc completo |
| `docs/data/audit-model.md` | De 1 línea a doc completo |
| `docs/roadmap/implementation-phases.md` | Corregido: Fases 6 y 7 con estado real, Fases 8-12 añadidas |
| `docs/risks/risk-register.md` | Añadidos R-15, R-16, R-17, R-18, R-E01, R-E02, R-E05 |
| `docs/risks/open-questions.md` | De 1 línea a lista completa de preguntas abiertas |
| `docs/risks/assumptions-to-avoid.md` | De 1 línea a lista completa |
| `docs/research/official-doc-checklist.md` | Expandido con todas las APIs del proyecto |
| `docs/research/validated-decisions.md` | De stub a lista completa de decisiones validadas |
| `docs/research/pending-validations.md` | Expandido con validaciones prioritizadas |
| `docs/operations/runbooks.md` | De 1 línea a runbooks operacionales completos |
| `docs/operations/support-model.md` | De 1 línea a modelo de soporte completo |
| `docs/operations/onboarding-tenants.md` | De 1 línea a proceso completo |
| `docs/operations/human-interventions.md` | Consolidado → redirige a HUMAN_INTERVENTIONS.md |

---

## Infraestructura activa (Supabase)

- **Proyecto**: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)
- **Tenant dev**: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **meta_waba_id**: `2159052118202272` ✅
- **11 migraciones aplicadas** (ver `docs/data/schema.md`)

Para ejecutar SQL desde la VM:
```bash
supabase db query --linked "SELECT * FROM tenants;"
supabase db query --linked -f supabase/migrations/archivo.sql
```
> `psql` directo NO funciona (Supavisor bloquea TCP)

---

## Estado de credenciales

| Token | Estado | Acción |
|-------|--------|--------|
| `META_ACCESS_TOKEN` | ✅ Permanente | System User `commerce-ops` — sin expiración (IH-006 ✅) |
| `GEMINI_API_KEY` | ✅ Configurada | Lista |
| `SUPABASE_JWT_SECRET` | ✅ Presente | Lista |

---

## Entorno VM (Oracle Linux 9)

- **Sin venv** — pip3 sistema (máquina dedicada)
- **Python**: 3.9.25 — usar `Optional[X]`, no `X | None` ⚠️ EOL
- **Node**: v20.20.2 via nvm, pnpm 10.33.0
- **Supabase CLI**: v2.84.2 en `/usr/local/bin/`

---

## Lecciones aprendidas críticas

1. `gemini-2.0-flash` NO disponible en cuentas nuevas. Usar `gemini-2.5-flash`.
2. `NODE_ENV=production` + `npm install` omite devDeps. Fix: `--include=dev`.
3. `apps/web` requiere `postcss.config.js` + autoprefixer en devDeps para TailwindCSS en prod.
4. `psql` TCP bloqueado por Supavisor. Usar `supabase db query --linked`.
5. `google-generativeai` está deprecated. Usar `google-genai==1.47.0`.
6. En triggers Supabase: `NEW.id` en tabla `tenant_users` es la PK de la fila, **no** el user_id. Siempre usar `NEW.user_id` para referenciar `auth.users.id`.
7. Después de cambiar `app_metadata` en Supabase Auth, el usuario debe hacer logout + login para obtener un JWT nuevo con los claims actualizados.

---

## Contexto documental ahora vigente

Luego de la actualización de esta sesión, el repositorio tiene documentación completa de:

- **Producto**: qué se construye, alcance, consolas, personas
- **Interfaz**: todos los módulos de Tenant Console y Platform Console con estados
- **Arquitectura**: mapeo frontend ↔ backend por módulo, conectores, async
- **Shipping/Courier**: diseño completo del módulo con Envia
- **Datos**: schema completo vigente y pendiente, RLS, auditoría
- **Roadmap**: fases 1-12 con estado real
- **Riesgos**: registro actualizado con Envia y producto
- **Operaciones**: runbooks, soporte, onboarding, intervenciones humanas

---

## Trabajo completado rev. 9 — Fases 8, 9 y 10 (2026-04-09)

### Fase 8 — Catálogo completo + RBAC base ✅

- ✅ `services/api/routers/products.py` reescrito para alinear con schema real (`title`/`status`/`product_variations`)
- ✅ RBAC en API: `get_current_role()` + `require_write_role()` en `services/api/dependencies/auth.py`
- ✅ Edición de producto + soft delete desde UI
- ✅ Sidebar ampliado: Pedidos, Contactos, Integraciones, Envíos, Configuración
- ✅ Botón logout + mensaje de error en login

### Fase 9 — Schema core + Pedidos + Config + Equipo ✅

- ✅ Migración `20260409220000_fase9_schema_core.sql` aplicada — 5 tablas nuevas: `contacts`, `orders`, `order_items`, `tenant_integrations`, `notification_settings`
- ✅ Migración `20260409230000_shipments.sql` aplicada — tabla `shipments`
- ✅ Routers nuevos: `orders.py`, `contacts.py`, `settings.py`
- ✅ UI nueva: `/dashboard/orders`, `/dashboard/contacts`, `/dashboard/settings`
- ✅ `get_tenant_team()` función SECURITY DEFINER para exponer emails de auth.users sin service_role

**Nota de tipo crítica**: Supabase retorna FK join de `contacts` como array (`Contact[]`), no objeto. El tipo en `orders/page.tsx` es `Contact | Contact[] | null` con guard `Array.isArray()`.

### Fase 10 — Integraciones MeLi + Envia ✅

- ✅ `services/api/integrations/meli_client.py` — OAuth 2.0 por tenant, URL country-specific via `MELI_AUTH_URL` env var
- ✅ `services/api/integrations/envia_client.py` — Bearer per-tenant, sandbox/prod configurable
- ✅ `services/api/routers/integrations.py` — endpoints connect/disconnect Envia y MeLi + callback OAuth
- ✅ `services/api/routers/shipping.py` — cotización + historial
- ✅ UI `/dashboard/integrations` — estado, connect/disconnect ambas integraciones
- ✅ UI `/dashboard/shipping` — banner si Envia no conectado, historial de cotizaciones
- ✅ MeLi OAuth URL construida en Server Component directamente (sin fetch al API intermediario)
- ✅ MeLi conectado: user_id `603780765` · Envia Sandbox conectado: Empresa #5017
- ✅ IH-007 (app MeLi) e IH-008 (API key Envia) completados

**Env vars requeridas en Render:**

| Var | Servicio |
|-----|----------|
| `MELI_CLIENT_ID` | web + api |
| `MELI_CLIENT_SECRET` | api |
| `MELI_REDIRECT_URI` | web + api |
| `MELI_AUTH_URL` | web + api |
| `API_URL` | web |

---

## Trabajo completado rev. 10 — Fase 11 + UI Redesign (2026-04-09)

### Fase 11 — Módulos restantes Tenant Console ✅ COMPLETADA

| Módulo | Ruta | Estado |
|--------|------|--------|
| Métricas | `/dashboard/metrics` | ✅ Completo |
| Inventario | `/dashboard/inventory` | ✅ Completo |
| Knowledge Base | `/dashboard/knowledge-base` | ✅ Completo |
| Auditoría | `/dashboard/audit` | ✅ Completo |
| Media | `/dashboard/media` | ✅ Completo |
| Webhook MeLi | `POST /api/v1/meli/webhook` | ✅ Completo |
| KB en Orchestrator | `tools/kb_tool.py` | ✅ Completo |

#### Migraciones aplicadas (Fase 11)

| Migración | Tabla | Estado |
|-----------|-------|--------|
| `20260409240000_stock_movements.sql` | `stock_movements` | ✅ Aplicada |
| `20260409250000_kb_documents.sql` | `kb_documents` | ✅ Aplicada |
| `20260409260000_audit_log.sql` | `audit_log` | ✅ Aplicada |

#### Detalle técnico por módulo

**Métricas** (`apps/web/app/dashboard/metrics/page.tsx`):
- Queries paralelas: mensajes 30d, conversaciones, pedidos, order_items, contactos, productos
- 4 KPI cards + pedidos por estado + top 5 productos por cantidad/revenue

**Inventario** (`apps/web/app/dashboard/inventory/page.tsx`):
- Stock por variación con atributos JSONB
- Alertas de stock bajo (≤ 5 unidades)
- Formulario de ajuste de stock → inserta en `stock_movements`
- `stock_movements`: delta + new_stock + reason + created_by + RLS por tenant

**Knowledge Base** (`apps/web/app/dashboard/knowledge-base/page.tsx`):
- CRUD completo con Server Actions: createDocument, toggleDocument, deleteDocument
- Categorías: faq, politica, negocio, producto, general
- `kb_documents`: title, content, category, is_active, updated_at trigger

**Auditoría** (`apps/web/app/dashboard/audit/page.tsx`):
- Filtro por entity_type (badges como links con query params)
- Paginación 25 items/página
- `<details>` expandible por entry con payload JSONB
- `audit_log`: action, entity_type, entity_id, payload JSONB, user_email snapshot

**Media** (`apps/web/app/dashboard/media/`):
- Server Component lista archivos desde Supabase Storage bucket `tenant-media`
- Client Component (`media-client.tsx`): upload, delete, copy public URL
- Validación: solo imágenes (JPEG/PNG/WebP/GIF), máx. 5MB
- Filename generado: `Date.now()-random.ext` evita colisiones
- RLS Storage: `(storage.foldername(name))[1] = auth.uid()` — tenant isolation por carpeta
- Tipo: `StorageFile.metadata` tipado como `{ size?: number | null; mimetype?: string | null } | null`

**Webhook MeLi** (`services/api/routers/meli_webhook.py`):
- `POST /api/v1/meli/webhook` — responde 200 inmediatamente, procesa en `BackgroundTask`
- Resolución de tenant: busca `meli_user_id` en `tenant_integrations.meta`
- Auto-refresh de token MeLi si expirado
- Crea/actualiza pedidos desde notificaciones `orders_v2`

**Knowledge Base en Orchestrator** (`services/ai-orchestrator/tools/kb_tool.py`):
- `get_tenant_kb()` — fetches active kb_documents
- `format_kb_for_prompt()` — agrupa por categoría, formatea como secciones markdown
- `orchestrator.py`: fetch catalog + KB + history en paralelo con `asyncio.gather()`
- KB section inyectada en system prompt después del catálogo

### UI Redesign — Dark Warm Theme ✅

Rediseño completo de la paleta de color y la navegación del sidebar.

#### Paleta de color (`apps/web/app/globals.css`)

| Variable | Valor HSL | Color |
|----------|-----------|-------|
| `--background` | `168 10% 10%` | `#181E1D` — carbón oscuro con alma verde |
| `--card` | `168 10% 13%` | `#1E2624` — levemente elevado |
| `--primary` | `155 52% 46%` | `#38A875` — verde bosque luminoso |
| `--foreground` | `36 25% 92%` | `#F0EDE8` — crema cálido |
| `--muted-foreground` | `168 10% 52%` | `#7A9490` — gris verdoso |
| `--border` | `168 10% 20%` | `#2A3533` |
| `--amber` | `42 75% 52%` | `#D4A843` — dorado ámbar |
| `--sidebar-bg` | `168 14% 8%` | `#131A19` — más oscuro que canvas |

Filosofía: oscuro CÓMODO — carbón cálido con tinte verde (no azul frío, no negro puro).
Referencia: Notion dark, GitHub dark dimmed, Bear App.

#### Utilidades CSS añadidas

- `.sidebar-gradient` — gradiente vertical para el sidebar
- `.glow-primary` — box-shadow verde sutil para el logo
- `.text-gradient` — degradado verde → dorado para títulos
- `.card-hover` — hover con borde primary/30 y shadow sutil

#### Sidebar RBAC Visual (`apps/web/app/dashboard/layout.tsx`)

- `NAV_ITEMS[]` con campo `roles: string[]` — array vacío = visible para todos
- `visibleItems = NAV_ITEMS.filter(item => item.roles.length === 0 || item.roles.includes(role))`
- Role badges: amber (owner), white/15 (manager), white/10 (agent)
- Top bar: `bg-card/80 backdrop-blur-sm` sticky
- Icons: color `text-white/60`, hover `text-amber-300`

#### Font fix

- Problema: `@import url(Google Fonts)` después de `@tailwind` rompe PostCSS en Next.js
- Solución: `next/font/google` en `apps/web/app/layout.tsx` con CSS variable `--font-inter`
- `tailwind.config.ts`: `fontFamily: { sans: ['var(--font-inter)', ...] }`

#### TypeScript fixes durante deploy

| Archivo | Error | Solución |
|---------|-------|---------|
| `dashboard/orders/page.tsx` | `contacts: Contact` vs array | Tipo: `Contact \| Contact[] \| null` + `Array.isArray()` guard |
| `dashboard/media/media-client.tsx` | `FileObject.metadata` no acepta null | Tipo: `{ size?: number \| null; mimetype?: string \| null } \| null` |
| `dashboard/media/page.tsx` | `FileObject[]` no asignable a `StorageFile[]` | Cast: `as any[]` |

### Fase 12 — Platform Console ❌ PENDIENTE

**Prerequisito bloqueante**: OQ-P01 — ¿misma app Next.js (`/platform/*`) vs app separada?

Requiere:
- Tabla `platform_users` con roles `platform_superadmin`, `platform_support`, `platform_ops`
- Auth diferenciada en `middleware.ts` para rutas `/platform/*`
- Endpoints platform-only en `services/api`

---

---

## Trabajo completado rev. 13 — Implementación de gaps críticos y altos (2026-04-09)

### Resumen

Se implementaron todos los gaps 🔴 CRÍTICOS y 🟠 ALTOS identificados en la sesión de revisión de producto. El repo ya no tiene ningún gap de prioridad roja ni naranja sin resolver en la Tenant Console.

### Archivos creados/modificados

| Archivo | Cambio |
|---------|--------|
| `services/api/integrations/whatsapp_sender.py` | CREADO — envío de mensajes de texto vía Meta Graph API (para agentes humanos) |
| `services/api/routers/conversations.py` | POST `/{id}/send` — agente envía mensaje cuando `human_takeover` + persiste en `messages` |
| `apps/web/app/dashboard/inbox/page.tsx` | Campo de texto + botón enviar cuando status=human_takeover; Realtime recoge el mensaje |
| `apps/web/app/dashboard/integrations/page.tsx` | Server Action `disconnectMeli` + formulario real (eliminado botón "próximamente") |
| `apps/web/app/dashboard/dashboard-client.tsx` | CREADO — Client Component con Tabs (Operaciones/Negocio) + gráficas recharts |
| `apps/web/app/dashboard/page.tsx` | Server Component con 11 queries paralelas → pasa datos a DashboardClient |
| `apps/web/app/dashboard/orders/orders-new-form.tsx` | CREADO — formulario multi-item dinámico Client Component con total automático |
| `apps/web/app/dashboard/orders/page.tsx` | Usa OrdersNewForm; advanceStatus llama API (para decremento de stock en confirm) |
| `services/api/routers/orders.py` | `patch_order` decrementa stock en `pending → confirmed` vía `_decrement_stock_on_confirm()` |
| `supabase/migrations/20260409270000_tenant_shipping_origin.sql` | CREADO + APLICADO — columnas `shipping_origin JSONB` y `logo_url TEXT` en `tenants` |
| `services/api/routers/settings.py` | `ShippingOrigin` modelo; `GET /tenant` incluye nuevos campos; `PATCH /tenant` soporta `shipping_origin` |
| `apps/web/app/dashboard/settings/page.tsx` | Sección "Dirección de origen" con formulario de 8 campos |
| `apps/web/app/dashboard/shipping/shipping-quote-form.tsx` | CREADO — formulario interactivo de cotización con tabla de selección de carrier |
| `apps/web/app/dashboard/shipping/page.tsx` | Integra ShippingQuoteForm + lee `shipping_origin` del tenant |

### Cambios de comportamiento importantes

| Módulo | Antes | Después |
|--------|-------|---------|
| Inbox AI | Takeover sin respuesta posible | Campo de texto + envío real vía Meta API cuando en takeover |
| Integraciones | Botón "Desconectar MeLi" deshabilitado | Server Action funcional — elimina tokens MeLi del tenant |
| Dashboard | 4 KPI cards estáticas | Tabs: Operaciones (urgencias clickables) + Negocio (gráficas recharts) |
| Pedidos | 1 producto hardcoded, sin decremento de stock | N productos dinámicos, total automático, stock decrementado al confirmar |
| Configuración | Sin dirección de origen | Formulario 8 campos, guardado en `tenants.shipping_origin` |
| Envíos | Placeholder "próximamente" | Formulario desplegable con origen pre-llenado, tabla de carriers, selección guarda `selected_rate` |

### Dependencia de env var

`NEXT_PUBLIC_API_URL` debe estar configurada en el servicio `web` de Render para que el Inbox (send message) y el formulario de nuevo pedido (multi-item) funcionen. Actualmente hardcodeado a `https://commerce-ops-api.onrender.com` como fallback.

---

## Trabajo completado rev. 14 — Gaps 🟡 MEDIA y 🟢 BAJA completados (2026-04-10)

### Resumen

Se completaron todos los gaps de prioridad media y baja de `docs/product/module-design-decisions.md`. La Tenant Console queda sin deuda técnica pendiente para llegar a Beta Controlada.

### Migraciones creadas (pendientes de aplicar via `supabase db query --linked`)

| Migración | Tabla/Columna | Estado |
|-----------|---------------|--------|
| `20260410010000_tenant_low_stock_threshold.sql` | `tenants.low_stock_threshold INT DEFAULT 5` | ⚠️ PENDIENTE aplicar |
| `20260410020000_contacts_consent.sql` | `contacts.consent_given BOOL`, `contacts.consent_date TIMESTAMPTZ` | ⚠️ PENDIENTE aplicar |

**Para aplicar:**
```bash
supabase db query --linked -f supabase/migrations/20260410010000_tenant_low_stock_threshold.sql
supabase db query --linked -f supabase/migrations/20260410020000_contacts_consent.sql
```

### Archivos creados/modificados

| Archivo | Cambio |
|---------|--------|
| `apps/web/app/dashboard/layout.tsx` | Sidebar muestra logo del tenant (img) o inicial; nombre del tenant en lugar de "Commerce Ops" |
| `apps/web/app/dashboard/settings/logo-upload.tsx` | CREADO — Client Component upload de logo a `tenant-media/{uid}/logo/`, guarda URL en `tenants.logo_url` |
| `apps/web/app/dashboard/settings/page.tsx` | Sección logo upload (owner-only) integrada en tarjeta "Información del Tenant" |
| `apps/web/app/dashboard/inventory/page.tsx` | Umbral configurable por tenant; fetches `tenants.low_stock_threshold`; nuevo formulario "Guardar umbral" |
| `apps/web/app/dashboard/metrics/page.tsx` | Filtros de período via `searchParams` (7d/30d/90d/todo); gráficas BarChart + PieChart |
| `apps/web/app/dashboard/metrics/metrics-filters.tsx` | CREADO — Client Component botones de período |
| `apps/web/app/dashboard/metrics/metrics-charts.tsx` | CREADO — Client Component recharts (MessagesBarChart + OrdersPieChart) |
| `apps/web/app/dashboard/audit/page.tsx` | Filtros por fecha (from/to), usuario (ilike), exportación CSV (owner-only) |
| `apps/web/app/api/audit/export/route.ts` | CREADO — Route Handler GET: genera CSV de audit_log respetando filtros activos |
| `apps/web/app/dashboard/knowledge-base/page.tsx` | Banner "modo inyección texto plano / RAG pendiente OQ-T03"; paleta dark theme |
| `apps/web/app/dashboard/contacts/page.tsx` | Campo `consent_given` en formularios (add + edit); banner Habeas Data; badges ShieldCheck/ShieldOff |
| `services/ai-orchestrator/orchestrator.py` | Paso 1.5: upsert de contacto al recibir mensaje WhatsApp (solo si no existe, `consent_given=false`) |
| `docs/risks/open-questions.md` | OQ-T03 expandido con plan RAG concreto (pgvector + migración + Gemini embeddings) |
| `supabase/migrations/20260410010000_tenant_low_stock_threshold.sql` | CREADO |
| `supabase/migrations/20260410020000_contacts_consent.sql` | CREADO |

### Cambios de comportamiento

| Módulo | Antes | Después |
|--------|-------|---------|
| Sidebar | Logo "CO" fijo, nombre "Commerce Ops" fijo | Logo real del tenant (o inicial); nombre del tenant |
| Configuración | Sin logo | Upload de logo a Storage + preview; guarda URL en `tenants.logo_url` |
| Inventario | Umbral fijo 5 unidades | Umbral configurable por tenant guardado en `tenants.low_stock_threshold` |
| Métricas | Período fijo 30 días, sin gráficas | Botones 7d/30d/90d/Todo; BarChart mensajes/día; PieChart pedidos por estado |
| Auditoría | Solo filtro por entidad, sin exportación | Filtros fecha (from/to) + usuario; exportación CSV (owner) |
| Knowledge Base | Sin indicador de modo de inyección | Banner "texto plano / RAG planificado OQ-T03" |
| Contactos | Sin campo de consentimiento | `consent_given` + `consent_date`; banner Habeas Data; icono por estado |
| Orchestrator | Contactos creados solo manualmente | Upsert automático al recibir primer mensaje WhatsApp (`consent_given=false`) |

### Estado de migraciones pendientes (IH)

⚠️ **Requiere intervención humana**: aplicar las 2 nuevas migraciones vía `supabase db query --linked`:
```
20260410010000_tenant_low_stock_threshold.sql
20260410020000_contacts_consent.sql
```
Hasta que se apliquen, `inventory/page.tsx` usará `DEFAULT_THRESHOLD=5` como fallback, y `contacts/page.tsx` puede fallar si la columna no existe.

---

## Trabajo completado rev. 12 — Revisión de producto por módulo (2026-04-09)

### Contexto

Se realizó una revisión exhaustiva de los 13 módulos de la Tenant Console con enfoque de **producto real y vendible**, no prototipo. El objetivo fue acercar cada módulo a la realidad operacional de un SaaS comercial, identificar gaps críticos y documentar la visión objetivo.

### Decisión de sesión crítica

> "Este proyecto NO es un prototipo, MVP, ni experimento — es algo real, masivo y vendible, pensado para X clientes reales."

Toda la deuda técnica identificada se documenta con esa vara.

### Gaps críticos identificados

| Módulo | Gap | Impacto |
|--------|-----|---------|
| Inbox AI | Agente puede tomar takeover pero NO puede enviar mensajes desde la consola | El módulo está funcionalmente incompleto |
| Integraciones | Botón "Desconectar MeLi" no existe | El tenant no puede desconectar su cuenta MeLi |
| Configuración | No hay dirección de origen de envíos | Bloquea formulario de cotización Envia |

### Nuevas decisiones de diseño

| Módulo | Decisión |
|--------|----------|
| Dashboard | Dos tabs: Operaciones (urgencia) y Negocio (tendencias + gráficas) |
| Media | NO fusionar con Inventario — mantener como biblioteca, añadir vinculación a productos |
| Pedidos ↔ Envíos | Envío nace desde Pedido (botón "Crear envío" en detalle). Envíos = historial cross-order |
| KB | Giro a RAG con pgvector — prerequisito: verificar OQ-T03 |
| Configuración | Branding del tenant: logo en sidebar, color primario opcional |
| Métricas vs Dashboard | Son complementarios, no redundantes. Métricas = módulo analítico profundo |

### Habeas Data Colombia — Decisión documentada

| Aspecto | Decisión |
|---------|----------|
| Plataforma | Encargada del tratamiento (Data Processor) |
| Tenant | Responsable del tratamiento (Data Controller) |
| Acción requerida antes de Beta | Campo `consent_given` en `contacts`, DPA con tenants, endpoint de eliminación |
| ¿Bloquea el desarrollo actual? | NO — pero es obligatorio antes del primer tenant real |

### Archivos modificados (rev. 12)

| Archivo | Cambio |
|---------|--------|
| `docs/product/module-design-decisions.md` | CREADO — visión objetivo detallada por módulo, análisis Habeas Data, tabla de deudas por impacto |
| `docs/product/admin-ui-modules.md` | Rev. 4 — `Visión objetivo` añadido a A.1-A.13; gaps críticos de Inbox AI e Integraciones MeLi registrados; Habeas Data en A.7 |
| `docs/HANDOFF.md` | Rev. 12 — esta sección |

---

## Trabajo completado rev. 11 — Gobernanza documental completa (2026-04-09)

### Problema detectado

Al auditar el repositorio se encontró que **AGENTS.md, current-scope.md, admin-ui-modules.md, navigation-map.md, front-back-separation.md y schema.md** seguían en rev. 7 (estado pre-Fase 8) mientras que el código ya tenía Fases 8-11 completadas. Los documentos contradecían completamente el estado real del repo.

### Contradicciones corregidas

| Documento | Contradicción | Corrección |
|-----------|--------------|------------|
| `AGENTS.md` | Fases 8-11 marcadas ❌ PENDIENTE | Actualizadas a ✅ COMPLETADAS; tabla de módulos reescrita |
| `docs/product/current-scope.md` | Todos los módulos TC mostrados como "No existe" | Reescrito completo: 11/13 módulos ✅, 2 🟡 |
| `docs/product/admin-ui-modules.md` | A.4-A.13 marcados ❌ Pendiente | 9 módulos actualizados a ✅/🟡 con evidencia real |
| `docs/product/navigation-map.md` | Solo 3 ítems en sidebar | Reescrito: 13 ítems, todas las rutas existen |
| `docs/integrations/courier-envia.md` | Estado: "Diseñado — pendiente" | Actualizado: Fase Inicial implementada (envia_client.py, shipping.py, UI, sandbox) |
| `docs/architecture/front-back-separation.md` | BLOQUEs 1-5 pendientes | BLOQUEs 1-5 marcados ✅; módulos A.4-A.13 actualizados |
| `docs/data/schema.md` | 6 migraciones, tablas como "pendientes" | 11 migraciones; tablas Fases 9-11 movidas a "vigentes" con schema real |
| `docs/risks/open-questions.md` | OQ-04, OQ-P04 abiertos; OQ-06 sin actualizar | OQ-04 cerrado (PV-03 resuelto); OQ-P04 cerrado; OQ-06 con propuesta post-Fase 11 |

### Archivos modificados (rev. 11)

| Archivo | Cambio |
|---------|--------|
| `AGENTS.md` | Rev. 11 — fases y módulos actualizados |
| `docs/HANDOFF.md` | Rev. 11 — sección de gobernanza añadida |
| `docs/product/current-scope.md` | Reescrito completo — estado real post Fase 11 |
| `docs/product/admin-ui-modules.md` | Rev. 3 — estados A.3-A.13 actualizados |
| `docs/product/navigation-map.md` | Rev. 3 — sidebar 13 ítems, todas las rutas |
| `docs/integrations/courier-envia.md` | Rev. 2 — Fase Inicial implementada; arquitectura actualizada |
| `docs/architecture/front-back-separation.md` | Rev. 8 — BLOQUEs 1-5 completados; módulos actualizados |
| `docs/data/schema.md` | Rev. 2 — 11 migraciones; tablas vigentes vs pendientes corregidas |
| `docs/risks/open-questions.md` | Rev. 8 — OQ-04 y OQ-P04 cerrados |

---

## Documentos de referencia

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

---

## Documentos de referencia

| Archivo | Contenido |
|---------|-----------|
| `AGENTS.md` | **Estado del sistema vigente** — leer primero siempre |
| `docs/product/current-scope.md` | Estado de implementación real hoy |
| `docs/product/personas-and-consoles.md` | Las dos consolas del producto |
| `docs/product/admin-ui-modules.md` | Módulos con estado por consola |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño Shipping/Courier |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-001 a IH-008 — todos completados excepto renovación periódica META_ACCESS_TOKEN |
| `docs/roadmap/implementation-phases.md` | Fases 1-12 con estado |
| `docs/risks/risk-register.md` | Riesgos activos |
| `docs/deployment/FASE7_RENDER_DEPLOY.md` | Guía de deploy en Render |
