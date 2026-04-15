# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-14 (rev. 17 — Revisión arquitectónica vuelta 1, restructuring-review ejecutado)
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
| shadcn/ui components | 5 componentes | En `apps/web/components/ui/`: badge, button, card, input, label |
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
| Ruff | `pyproject.toml` | Linter — E, F, W, I, B, C — line-length 100 |

---

## Resumen Ejecutivo de Implementación

| Capa | Estado |
|---|---|
| Tenant Console — Módulos | ✅ Live (ver tabla abajo) |
| Navegación Sidebar | ✅ Reestructurada con Route Groups + grupos expandibles RBAC |
| Platform Console | ❌ No existe — bloqueante OQ-P01 no resuelto |
| Backend API | ✅ 3 servicios live + 9 routers |
| Base de datos | ✅ 20 migraciones aplicadas |
| Deploy Render | ✅ 4 servicios live |
| Envia / Shipping | 🟡 Fase Inicial — quote + historial live. Label/tracking: Fase 2 |
| MeLi | 🟡 Fase Inicial — OAuth + webhook + listings operativos. Sync bidireccional: pendiente |

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
| Configuración (General) | `/dashboard/settings` | ✅ Live | Datos del negocio, logo, WABA, dirección de origen, Telegram |
| Usuarios y Acceso | `/dashboard/team` | ✅ Live | Equipo RBAC: listado, changeRole, removeMember. Extraído de settings en Vuelta 5 |
| Integraciones | `/dashboard/integrations` | ✅ Live | MeLi + Envia connect/disconnect |

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

> Fuente canónica: `supabase/migrations/`. `packages/db/migrations/` es copia parcial desincronizada — ignorar.

---

## Deuda Técnica Activa

| Ítem | Prioridad |
|---|---|
| Sync bidireccional catálogo ↔ MeLi listings | Media |
| Envia Fase 2: label, tracking, pickup | Media |
| WhatsApp Config centralizada (templates aprobados, WABA management) | Media |
| ~~Reclamos — acciones reales~~ | ✅ Resuelto Vuelta 3 |
| ~~Agentes IA — desbloquear en sidebar~~ | ✅ Resuelto Vuelta 3 |
| ~~Dashboard — usar `tenants.low_stock_threshold` dinámico~~ | ✅ Resuelto Vuelta 3 |
| ~~Dashboard KPIs — eliminar trends hardcodeados~~ | ✅ Resuelto Vuelta 3 |

---

## Bloqueos Activos

| Bloqueante | Tipo | Impacto |
|---|---|---|
| OQ-P01 sin decidir (arquitectura Platform Console) | Decisión pendiente | Bloquea Fase 12 — sin impacto en Tenant Console |

---

## Política de Actualización

- Actualizar este archivo al cierre de cada sesión de trabajo.
- No duplicar estado en múltiples archivos. Este es el único lugar.
- No incluir aquí intenciones ni roadmap — eso es `docs/roadmap/` y `.context/04-next-steps.md`.
- Los docs eliminados en sesiones previas no deben reaparecer en referencias.
