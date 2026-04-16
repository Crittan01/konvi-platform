# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-15 (rev. 20 — Vuelta 7: Configuración CERTIFICADA con 2 pendientes, flujo invite corregido implicit flow, agent→operator, JWT invalidación en changeRole)
**Fuente de verdad**: código en el repo, no documentación previa ni intenciones.
**Tree funcional vigente**: `.context/00-product.md`

---

## Stack Real Vigente

### Frontend — `apps/web`

| Elemento | Versión real | Notas |
|---|---|---|
| Next.js | **14.2.35** | CVE patch aplicado (14.1.0 → 14.2.35) |
| React | ^18 | — |
| TypeScript | ^5 | strict + strictNullChecks + noImplicitAny |
| TailwindCSS | ^3.3.0 | `postcss.config.js` + `autoprefixer` en devDeps (fix Render) |
| shadcn/ui components | 11 componentes | En `apps/web/components/ui/` (accordion, badge, button, card, dialog, input, label, select, sheet, tabs, textarea) |
| `@supabase/ssr` | ^0.10.0 | — |
| Patrón routing | App Router + Route Groups | `(sales)`, `(products)`, `(channels)`, `(ai)`, `(analytics)`, `(settings-group)` |
| Server Actions | Sí | catalog, knowledge-base, inventory, orders, contacts |
| Font | Inter via `next/font/google` | CSS variable `--font-inter` |
| Prettier | `.prettierrc.json` | Formato estándar — singleQuote, trailing comma |
| ESLint | `eslint@8` + `@typescript-eslint/recommended` | `.eslintrc.json` — next/core-web-vitals base |

> `packages/ui` está vacío. Componentes en `apps/web/components/ui/`.

### Backend — Python

| Elemento | Versión real | Notas |
|---|---|---|
| Python | **3.11.13** | Oracle Linux 9, instalado vía dnf, sin venv |
| FastAPI | 0.128.8 | Todos los servicios |
| Pydantic | 2.12.5 | — |
| google-genai | 1.47.0 | SDK oficial — `google-generativeai` DESINSTALADO |
| supabase-py | 2.28.3 | — |
| PyJWT | 2.10.1 | Solo en `services/api` |
| httpx | 0.28.1 | Estandarizado en todos los servicios Python (Render v4) |
| Ruff | `pyproject.toml` | Linter — E, F, W, I, B, C — line-length 100 |

---

## Resumen Ejecutivo de Implementación

| Capa | Estado |
|---|---|
| Tenant Console — Módulos | ✅ Live (ver tabla abajo) |
| Navegación Sidebar | ✅ Reestructurada con Route Groups + grupos expandibles RBAC |
| Platform Console | ❌ No existe — bloqueante OQ-P01 no resuelto |
| Backend API | ✅ 3 servicios live + 9 routers |
| Base de datos | ✅ 22 migraciones aplicadas |
| Deploy Render | ✅ 4 servicios live |
| Envia / Shipping | 🟡 Fase Inicial — quote + historial live. Label/tracking: Fase 2 |
| MeLi | 🟡 Fase Inicial — OAuth + webhook + listings operativos. Sync bidireccional: pendiente |
| Configuración | 🟡 Certificado (2 pendientes) | General ✅ Equipo ✅ Integraciones ✅ — pendiente: validar invite flow en Render + SMTP propio |

---

## Estado por Módulo — Tenant Console

| Módulo | Ruta | Estado | Notas |
|---|---|---|---|
| Dashboard | `/dashboard` | ✅ Live | Tabs Ops/Negocio — 11 queries paralelas — umbral dinámico por tenant |
| Inbox | `/dashboard/inbox` | ✅ Live | Realtime, human takeover, envío como agente |
| Pedidos | `/dashboard/orders` | ✅ Live | Listado, detalle, estados, stock decrementado al confirmar |
| Contactos | `/dashboard/contacts` | ✅ Live | Listado, perfil, consent Habeas Data |
| Reclamos | `/dashboard/claims` | ✅ Live | Crear reclamo, cambiar estado, vincular pedido. Fix: getUser + tenant_id |
| Catálogo | `/dashboard/catalog` | ✅ Live | CRUD, multi-variante, archivados, auto-refresh |
| Inventario | `/dashboard/inventory` | ✅ Live | Stock por variante, umbral configurable, ajuste con motivo |
| Media | `/dashboard/media` | ✅ Live | Upload/delete/URL via Supabase Storage `tenant-media` |
| Mercado Libre | `/dashboard/marketplace` | ✅ Live | Listings MeLi, sync stock, vinculación variation↔listing |
| Despachos (Envia) | `/dashboard/shipping` | ✅ Live | Cotizaciones + historial — renombrado de "Envíos" |
| Órdenes de Compra | `/dashboard/purchases` | ✅ Live | POs, proveedores, WAC |
| P&L / Finanzas | `/dashboard/finance` | ✅ Live | P&L Dashboard, Registro OPEX |
| Base de Conocimiento | `/dashboard/knowledge-base` | ✅ Live | CRUD, categorías, toggle activo, inyectada en Orchestrator |
| Agentes IA | `/dashboard/ai-agents` | ✅ Live | Directrices, roles, RAG parameters — **desbloqueado en sidebar** |
| Métricas | `/dashboard/metrics` | ✅ Live | 4 KPIs, filtros período, BarChart + PieChart |
| Auditoría | `/dashboard/audit` | ✅ Live | Filtros fecha/usuario, paginación, exportación CSV |
| Configuración (General) | `/dashboard/settings` | ✅ Live | Identidad: Nombre+Email+Celular obligatorios, NIT opcional, `+57` fijo, pattern `3[0-9]{9}`. Dirección origen: País bloqueado Colombia, select dpto→municipio DANE sin buscador libre |
| Usuarios y Acceso | `/dashboard/team` | ✅ Live | Roles: Administrador/Supervisor/Gestor (Lucide icons). Invite→/auth/confirm→/set-password. changeRole invalida JWT via admin.signOut(). Guard owner único. DB: agent→operator migrado |
| Integraciones | `/dashboard/integrations` | ✅ Live | 3 secciones: Logística/Marketplace/Notificaciones. Instructivos inline para Envia, MeLi y Telegram. testTelegram lee token desde DB, feedback por código de error HTTP |

---

## Estructura de Directorios Frontend (Real)

```
apps/web/app/
├── page.tsx                       ✅ Landing / redirect
├── layout.tsx                     ✅ Root layout (Inter font, globals.css)
├── globals.css                    ✅ Dark Warm Theme — HSL tokens
├── login/page.tsx                 ✅ Auth Supabase SSR
└── dashboard/
    ├── layout.tsx                 ✅ Shell: Sidebar + Main + top bar
    ├── page.tsx                   ✅ Dashboard RSC — 11 queries paralelas
    ├── dashboard-client.tsx       ✅ Tabs Ops/Negocio + recharts
    ├── sidebar-client.tsx         ✅ NAV_ITEMS — árbol de navegación
    ├── error.tsx                  ✅ Error boundary
    ├── inbox/                     ✅ Realtime WhatsApp
    ├── finance/                   ✅ P&L
    ├── purchases/                 ✅ Compras
    ├── (sales)/                   Route Group — /orders, /contacts, /shipping, /claims
    ├── (products)/                Route Group — /catalog, /inventory, /media
    ├── (channels)/                Route Group — /marketplace
    ├── (ai)/                      Route Group — /knowledge-base, /ai-agents
    ├── (analytics)/               Route Group — /metrics, /audit
    └── (settings-group)/          Route Group — /settings, /integrations
```

---

## Backend Services — Estado Real

| Servicio | URL Render | Estado |
|---|---|---|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (no URL pública — /health interno) | ✅ Live, polling 3s |

### Routers Activos en `services/api`

| Router | Endpoints clave | Estado |
|---|---|---|
| `products.py` | `GET/POST /products`, `PUT/DELETE /products/{id}`, `PATCH/POST/DELETE /variations/{id}` | ✅ |
| `orders.py` | `GET/POST /orders`, `PATCH /orders/{id}` | ✅ |
| `contacts.py` | `GET/POST /contacts` | ✅ |
| `settings.py` | `GET/PUT /settings`, `GET/POST/DELETE /team` | ✅ |
| `integrations.py` | `/integrations/envia`, `/integrations/meli`, OAuth callback | ✅ |
| `shipping.py` | `POST /shipping/quote`, `GET /shipping/history` | ✅ |
| `meli_webhook.py` | `POST /meli/webhook` | ✅ |
| `conversations.py` | `GET /conversations` | ✅ |
| `marketplace.py` | `GET/POST /marketplace`, `PATCH /marketplace/{id}/status` | ✅ |

### Endpoints Pendientes

| Endpoint | Fase | Estado |
|---|---|---|
| `POST /shipping/label` | Envia Fase 2 | 🔒 Pendiente |
| `GET /shipping/tracking/{id}` | Envia Fase 2 | 🔒 Pendiente |
| `POST /shipping/pickup` | Envia Fase 2 | 🔒 Pendiente |
| Endpoints platform-only | Fase 12 | ❌ Fuera de alcance actual |

---

## Base de Datos — Migraciones (20 aplicadas)

| Tabla principal | Migración | Estado |
|---|---|---|
| `tenants`, `tenant_users` | 20260406181235 | ✅ |
| `products`, `product_variations` | 20260406181236 | ✅ |
| `conversations`, `messages` | 20260406181237 | ✅ |
| `rls_policies` | 20260406181238 | ✅ |
| `contacts`, `orders`, `order_items`, `tenant_integrations`, `notification_settings` | 20260409220000 | ✅ |
| `shipments` | 20260409230000 | ✅ |
| `stock_movements` | 20260409240000 | ✅ |
| `kb_documents` | 20260409250000 | ✅ |
| `audit_log` | 20260409260000 | ✅ |
| `tenant_shipping_origin` | 20260409270000 | ✅ |
| `tenants.low_stock_threshold` | 20260410010000 | ✅ |
| `contacts.consent_given/consent_date` | 20260410020000 | ✅ |
| Catalog enterprise fields | 20260411162042 | ✅ |
| `ai_agents`, `ai_agent_documents` (pgvector) | 20260412000000 | ✅ |
| `purchase_orders`, `suppliers`, `finance_entries` | 20260413000000 | ✅ |
| Finance polish | 20260413000001 | ✅ |
| `marketplace_listings` | 20260413000002 | ✅ |
| `claims` | 20260413150000 | ✅ |
| RLS `tenant_users` + `add_member_to_tenant` | 20260415000000 | ✅ |
| `get_tenant_team` return confirmed status | 20260415010000 | ✅ |
| `tenants.nit`, `email_contacto`, `telefono_contacto` | 20260415020000 | ✅ |
| `tenant_users.role` `agent→operator`, `add_member_to_tenant` con roles renombrados | 20260415030000 | ✅ |

> Fuente canónica: `supabase/migrations/`. `packages/db/migrations/` es copia parcial desincronizada — ignorar.

---

## Artefactos Nuevos — Vuelta 7 (2026-04-15)

| Artefacto | Ruta | Descripción |
|-----------|------|-------------|
| Auth Confirm page (Client) | `apps/web/app/auth/confirm/page.tsx` | **Reemplaza route.ts**. Client Component con Suspense. Maneja implicit flow (`#access_token=` via createBrowserClient), PKCE (`?code=`) y OTP (`?token_hash=`). El Route Handler no puede leer el fragment URL. |
| Migración roles | `supabase/migrations/20260415030000_rename_agent_to_operator.sql` | Renombra `agent→operator` en `tenant_users`. Actualiza `add_member_to_tenant` para aceptar `owner/manager/operator`. **Aplicada en Supabase** |

---

## Artefactos Nuevos — Vuelta 6 (2026-04-15)

| Artefacto | Ruta | Descripción |
|-----------|------|-------------|
| Dataset DANE | `apps/web/lib/dane-colombia.ts` | 33 departamentos + 1.103 municipios DIVIPOLA. Función `getMunicipiosByDpto(codigo)` |
| ShippingOriginForm | `apps/web/app/dashboard/(settings-group)/settings/shipping-origin-form.tsx` | Client Component con select dependiente dpto→municipio. Guarda nombre (no código DANE) para compatibilidad Envia |
| Auth Confirm route | `apps/web/app/auth/confirm/route.ts` | Route handler GET. Maneja `token_hash` (OTP) y `code` (PKCE). Param `?next=/ruta` para redirect post-verificación |
| Set Password page | `apps/web/app/set-password/page.tsx` | Server Component. Valida sesión activa, form contraseña (min 8 chars, confirmación), Server Action `updateUser`. Redirect a `/dashboard` |
| Migración identidad | `supabase/migrations/20260415020000_tenant_identity_fields.sql` | Agrega `nit`, `email_contacto`, `telefono_contacto` a tabla `tenants`. **Aplicada en Supabase** |

## Intervenciones Humanas Pendientes

### ~~IH-SUPABASE-REDIRECT~~ ✅ RESUELTA
Site URL cambiado a `https://commerce-ops-web.onrender.com`. Redirect URLs incluyen `/auth/confirm` y `/set-password`. Resuelto 2026-04-15.

### IH-SMTP — SMTP custom con dominio propio (pendiente dominio)
**RESPONSABLE**: Arquitecto técnico
**ESTADO**: Supabase default SMTP activo (3 emails/hora). Custom SMTP habilitado temporalmente con Brevo pero revertido — Gmail sender bloqueado por DMARC `p=reject`.
**CUANDO**: Al tener dominio propio verificado.
**PASOS**:
1. Resend.com → Domains → verificar dominio propio
2. Resend.com → API Keys → crear key con scope `Sending access`
3. Supabase → Auth → SMTP → Enable Custom SMTP
4. Host: `smtp.resend.com` | Port: `465` | User: `resend` | Password: API Key
5. Sender: `noreply@tudominio.com`
**CRITERIO DE ÉXITO**: Invitación llega en <1 minuto sin rate limit.

### IH-INVITE-VALIDATE — Validar flujo completo de invitación en Render
**RESPONSABLE**: Arquitecto técnico
**PASOS**:
1. Desde `/dashboard/team` → invitar nuevo email
2. Abrir email → clic en enlace (debe apuntar a `commerce-ops-web.onrender.com`)
3. Browser carga `/auth/confirm#access_token=...`
4. Client Component lee hash → detecta sesión → redirige a `/set-password`
5. Usuario crea contraseña → accede a `/dashboard`
**CRITERIO DE ÉXITO**: Flujo completo sin errores en Render (no localhost).

---

## Deuda Técnica Activa

| Ítem | Prioridad |
|---|---|
| Sync bidireccional catálogo ↔ MeLi listings | Media |
| Envia Fase 2: label, tracking, pickup | Media |
| WhatsApp Config centralizada (templates aprobados, WABA management) | Media |
| Invite de miembros via formulario UI | Media — IH-001 requerida (APP_URL en Render) + IH-SMTP (SMTP custom Supabase con Resend, ver IH-003) |
| SMTP Supabase Free (3 emails/hora) → configura SMTP propio con Resend | Alta — bloquea invitaciones en producción con volumen |
| ~~Reclamos — acciones reales~~ | ✅ Resuelto Vuelta 3 |
| ~~Agentes IA — desbloquear en sidebar~~ | ✅ Resuelto Vuelta 3 |
| ~~Dashboard — usar `tenants.low_stock_threshold` dinámico~~ | ✅ Resuelto Vuelta 3 |
| ~~Dashboard KPIs — eliminar trends hardcodeados~~ | ✅ Resuelto Vuelta 3 |
| ~~`tenant_users` sin RLS~~ | ✅ Resuelto Vuelta 5 — migración 20260415000000 |
| ~~`logo-upload.tsx` `getSession()` inseguro~~ | ✅ Resuelto Vuelta 5 — `getUser()` |
| ~~Security Headers ausentes en Next.js~~ | ✅ Resuelto Vuelta 5 — `next.config.js` |
| ~~`low_stock_threshold` sin UI editable~~ | ✅ Resuelto Vuelta 5 — en General |
| ~~Configuración: sección Identidad sin NIT/email/teléfono~~ | ✅ Resuelto Vuelta 6 — migración 20260415020000 |
| ~~Dirección de origen: ciudad/dpto texto libre~~ | ✅ Resuelto Vuelta 6 — selects DANE DIVIPOLA (33 dptos, 1.103 municipios) |
| ~~Umbral stock bajo en sección incorrecta (Identidad)~~ | ✅ Resuelto Vuelta 6 — movido a sección "Configuración Operativa" |
| ~~Telegram en General Settings~~ | ✅ Resuelto Vuelta 6 — movido a Integraciones como card propia |
| ~~testTelegram silencioso (catch null, token en DOM)~~ | ✅ Resuelto Vuelta 6 — lee token desde DB, feedback explícito con código de error Telegram |
| ~~Roles con emojis (no renderizan en Linux/algunos browsers)~~ | ✅ Resuelto Vuelta 6 — íconos Lucide (Crown, Briefcase, Headphones) |
| ~~Roles con nombres genéricos (Owner/Manager/Operador)~~ | ✅ Resuelto Vuelta 6 — Administrador/Supervisor/Gestor (valores DB sin cambio) |
| ~~Flujo invitación sin página set-password~~ | ✅ Resuelto Vuelta 6 — /auth/confirm route + /set-password page |
| ~~Roles DB: valor 'agent' obsoleto~~ | ✅ Resuelto Vuelta 7 — migración 20260415030000 renombra agent→operator en tenant_users y add_member_to_tenant |
| ~~14 archivos frontend con fallback `?? 'agent'`~~ | ✅ Resuelto Vuelta 7 — todos actualizados a `?? 'operator'` |
| ~~JWT stale claims tras cambio de rol~~ | ✅ Resuelto Vuelta 7 — changeRole llama admin.signOut(userId,'global') para invalidar JWT activo |
| ~~`/auth/confirm` Route Handler no recibe `#access_token=`~~ | ✅ Resuelto Vuelta 7 — route.ts eliminado; page.tsx Client Component con createBrowserClient lee hash automáticamente |
| SMTP Supabase Free (3 emails/hora) → configurar SMTP propio con Resend | Alta — requiere dominio propio. Gmail bloqueado por DMARC p=reject |
| Validar flujo de invite completo en Render | Alta — IH-INVITE-VALIDATE pendiente |

---

## Bloqueos Activos

| Bloqueante | Tipo | Impacto |
|---|---|---|
| OQ-P01 sin decidir (arquitectura Platform Console) | Decisión pendiente | Bloquea Fase 12 — sin impacto en Tenant Console |
| IH-SMTP — SMTP custom con Resend (requiere dominio propio) | Intervención humana pendiente | Rate limit 3 emails/hora en Free. Gmail sender rechazado por DMARC. Pendiente hasta tener dominio. |
| IH-INVITE-VALIDATE — Validar flujo invitación completo en Render | Intervención humana pendiente | Confirmar que page.tsx Client Component lee #access_token= correctamente en producción |

---

## Seguridad y Cumplimiento (Verificado)

| Capa | Estado | Notas |
|---|---|---|
| **RLS** | ✅ Activo | Todas las tablas del esquema `public` tienen RLS habilitado y políticas por `tenant_id`. |
| **CORS** | ✅ Activo | Configurado en `services/api/main.py` restringido a `ALLOWED_ORIGINS`. |
| **Security Headers** | ✅ Activo | Implementado en `next.config.js` (CSP, HSTS, X-Frame-Options, X-Content-Type-Options). |
| **Audit Log** | ✅ Activo | Captura de cambios críticos en DB vía triggers/funciones. |

---

## Política de Actualización

- Actualizar este archivo al cierre de cada sesión de trabajo.
- No duplicar estado en múltiples archivos. Este es el único lugar.
- No incluir aquí intenciones ni roadmap — eso es `docs/roadmap/` y `.context/04-next-steps.md`.
- Los docs eliminados en sesiones previas no deben reaparecer en referencias.
