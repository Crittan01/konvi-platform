# Handoff — Estado del Proyecto al 2026-04-10

Este documento es el punto de entrada para retomar trabajo. **Leer antes de cualquier otra acción.**

---

## Sistema en una línea

**Commerce Ops Platform** — SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp. El LLM (Gemini) es asistencia controlada, nunca fuente de verdad de datos operacionales.

---

## Stack real en repo

| Capa | Versión real |
|------|-------------|
| Frontend | Next.js **14.2.35**, React ^18, TailwindCSS ^3.3.0 |
| Backend | Python **3.9.25** (EOL), FastAPI 0.128.8, google-genai 1.47.0 |
| DB / Auth | Supabase — 13 migraciones aplicadas, RLS + JWT Claims |
| IA | `gemini-2.5-flash` via `google-genai==1.47.0` |
| Hosting | Render — 4 servicios live (Free plan) |

> `packages/ui` está vacío. Componentes en `apps/web/components/ui/`.  
> Fuente de verdad de versiones: `package.json` y `requirements.txt`.

---

## Fases completadas

| Fase | Descripción | Estado |
|------|-------------|--------|
| 1-2 | Base monorepo + Auth/RLS Supabase | ✅ |
| 3a-3b | Foundation UI + WhatsApp Connector | ✅ |
| 4-5 | AI Orchestrator + Inbox AI Realtime | ✅ |
| 6-7 | API Gateway + Deploy Render + E2E confirmado | ✅ |
| 8 | Catálogo completo + RBAC base | ✅ |
| 9 | Schema core + Pedidos + Configuración + Equipo | ✅ |
| 10 | Integraciones MeLi + Envia/Shipping | ✅ |
| 11 | Módulos restantes Tenant Console + UI Redesign | ✅ |

---

## Tenant Console — Estado de módulos (13/13)

| Módulo | Ruta | Estado |
|--------|------|--------|
| Dashboard | `/dashboard` | ✅ Tabs Operaciones + Negocio, KPIs, gráficas recharts |
| Inbox AI | `/dashboard/inbox` | ✅ Realtime, human takeover, envío de mensajes como agente |
| Catálogo | `/dashboard/catalog` | ✅ CRUD + edición + soft delete (variantes múltiples: deuda) |
| Pedidos | `/dashboard/orders` | ✅ Listado, multi-item form, estados, stock decrementado al confirmar |
| Contactos | `/dashboard/contacts` | ✅ Listado, consent_given (Habeas Data), auto-upsert desde WhatsApp |
| Inventario | `/dashboard/inventory` | ✅ Stock por variante, umbral configurable por tenant, ajuste con motivo |
| Knowledge Base | `/dashboard/knowledge-base` | ✅ CRUD, categorías, toggle activo, inyectada en Orchestrator |
| Media | `/dashboard/media` | ✅ Upload/delete/URL via Supabase Storage `tenant-media` |
| Envíos | `/dashboard/shipping` | ✅ Historial + formulario interactivo de cotización (ShippingQuoteForm) |
| Integraciones | `/dashboard/integrations` | ✅ MeLi OAuth + Envia, connect/disconnect funcional |
| Métricas | `/dashboard/metrics` | ✅ KPIs, filtros de período, BarChart + PieChart |
| Auditoría | `/dashboard/audit` | ✅ Filtros fecha/usuario, paginación, exportación CSV |
| Configuración | `/dashboard/settings` | ✅ Equipo RBAC, logo tenant, dirección origen envíos, Telegram |

---

## Platform Console

**Estado**: ❌ No existe en absoluto. Cero rutas, cero layout, cero auth de plataforma.

**Prerequisito bloqueante**: OQ-P01 — ¿misma app Next.js (`/platform/*`) vs app separada?

---

## Infraestructura activa

| Servicio | URL | Estado |
|----------|-----|--------|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | background worker | ✅ Live, polling 3s |

- **Supabase**: `xmelwnhhphksbpdjmbbp` (us-east-1)
- **Tenant dev**: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **meta_waba_id**: `2159052118202272`
- **13 migraciones aplicadas** (ver `docs/data/schema.md`)

Para ejecutar SQL:
```bash
supabase db query --linked -f supabase/migrations/archivo.sql
# psql directo NO funciona (Supavisor bloquea TCP)
```

---

## Credenciales activas

| Token | Estado |
|-------|--------|
| `META_ACCESS_TOKEN` | ✅ Permanente — System User `commerce-ops`, sin expiración |
| `GEMINI_API_KEY` | ✅ Configurada, billing activo |
| `SUPABASE_JWT_SECRET` | ✅ Presente |

---

## Trabajo de la última sesión (2026-04-10)

### Hardening de seguridad y estabilidad

| Fix | Detalle |
|-----|---------|
| `getSession()` → `getUser()` | Todos los Server Components — previene JWT spoofing |
| Next.js `14.1.0` → `14.2.35` | Parchea 1 CVE crítico (middleware auth bypass) + 6 high |
| ESLint `^10` → `8.x` | Compatible con Next.js 14 lint runner |
| Error boundaries | `app/error.tsx` + `app/dashboard/error.tsx` — el error digest genérico ahora muestra UI recuperable |
| `logo-upload.tsx` tenantId prop | Fix bug: `app_metadata` no expone claims custom en SDK cliente — se pasa como prop explícita |
| AbortController timeouts | `advanceStatus` (15s), inbox send (15s), shipping quote (20s) — evita cuelgues con Render Free |
| Migraciones DB aplicadas | `tenants.low_stock_threshold` + `contacts.consent_given/consent_date` |
| Fix RSC function props | `onCreated/onQuoted/onSaved` como opcional con default interno — elimina error de serialización |

### Fix del error "Application error" en Catálogo, Pedidos, Envíos, Configuración

**Causa**: Funciones arrow `() => {}` pasadas como props de Server Components a Client Components no son serializables en React RSC — lanzaban excepción en runtime.

**Fix**: props opcionales con default `() => {}` dentro del Client Component; removidas del Server Component.

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

---

## Próximo paso

**Fase 12 — Platform Console**

1. Decidir OQ-P01: ¿`/platform/*` en la misma app vs app separada?
2. Diseñar tabla `platform_users` (roles: `platform_superadmin`, `platform_support`, `platform_ops`)
3. Auth diferenciada en `middleware.ts` para rutas `/platform/*`
4. Endpoints platform-only en `services/api`

Ver módulos completos en `docs/roadmap/implementation-phases.md` — Fase 12.

---

## Lecciones críticas (no repetir)

1. `gemini-2.0-flash` NO disponible en cuentas nuevas → usar `gemini-2.5-flash`
2. `NODE_ENV=production` + `npm install` omite devDeps → fix: `--include=dev`
3. `apps/web` requiere `postcss.config.js` + autoprefixer en devDeps para Tailwind en Render
4. `psql` TCP bloqueado por Supavisor → usar `supabase db query --linked`
5. `google-generativeai` deprecated → usar `google-genai==1.47.0`
6. Trigger `tenant_users`: `NEW.id` es la PK de la fila, no el user_id → usar `NEW.user_id`
7. Después de cambiar `app_metadata`, el usuario debe logout + login para JWT nuevo
8. `getSession()` en Server Components es inseguro — siempre usar `getUser()`
9. Funciones arrow `() => {}` no son serializables como props de RSC → usar props opcionales con default interno
10. ESLint v10 incompatible con Next.js 14 → usar `eslint@8`

---

## Referencias rápidas

| Archivo | Contenido |
|---------|-----------|
| `AGENTS.md` | Estado del sistema vigente — leer primero |
| `docs/product/current-scope.md` | Estado de implementación real verificado |
| `docs/product/admin-ui-modules.md` | Módulos con estado por consola |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño Shipping/Courier |
| `docs/risks/open-questions.md` | Preguntas abiertas y bloqueantes |
| `docs/roadmap/implementation-phases.md` | Fases 1-13 con estado |
