# Handoff — Estado del Proyecto al 2026-04-17 (rev. 22)

Este documento es el punto de entrada para retomar trabajo en infra y operación.
**Leer `.context/00-product.md` y `.context/01-state.md` antes si el foco es funcional o de código.**

---

## Sistema en una línea

**Commerce Ops Platform** — SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp.
El LLM (Gemini) es asistencia controlada, nunca fuente de verdad de datos operacionales.

---

## Stack real en repo

| Capa | Versión real |
|---|---|
| Frontend | Next.js **14.2.35**, React ^18, TailwindCSS ^3.3.0 |
| Backend | Python **3.11.13** (dnf, sin venv), FastAPI 0.128.8, google-genai 1.47.0 |
| DB / Auth | Supabase — 25 migraciones aplicadas, RLS + JWT Claims |
| IA | `gemini-2.5-flash` via `google-genai==1.47.0` |
| Hosting | Render — 4 servicios live (Free plan) |

---

## Fases completadas

| Fases | Descripción | Estado |
|---|---|---|
| 1-6 | Base monorepo + Auth/RLS + UI + WhatsApp + AI + API Gateway | ✅ |
| 7 | Deploy Render + E2E confirmado | ✅ |
| 8 | Catálogo completo + RBAC base | ✅ |
| 9 | Schema core + Pedidos + Configuración + Equipo | ✅ |
| 10 | Integraciones MeLi + Envia/Shipping | ✅ |
| 11 | Módulos restantes Tenant Console + UI Enterprise | ✅ |
| 11.1 | UI Plus Total + Route Groups + linting hardening | ✅ 2026-04-14 |
| 11.5 | Reclamos + Compras + Finanzas + Marketplace (Fase Enterprise completa) | ✅ 2026-04-15 |
| 11.6 | Integraciones modulares por tenant + Realtime Inbox + UX no-conectado | ✅ 2026-04-17 |

---

## Tenant Console — Estado de módulos

Ver tabla completa → `.context/01-state.md`

Resumen: 18 módulos live. Configuración ✅ certificada. Flujo invite validado en Render con usuario real. Integraciones 4/4 (WhatsApp, MeLi, Envia, Telegram) completamente modulares por tenant. Pendiente solo SMTP propio cuando haya dominio.

---

## Platform Console

**Estado**: ❌ No existe. Cero rutas, cero layout, cero auth de plataforma.
**Prerrequisito bloqueante**: OQ-P01 — ¿misma app Next.js (`/platform/*`) vs app separada?
**No se toca en la iniciativa actual.**

### Qué debe gestionar Platform Console cuando se construya

#### Gestión de tenants
- Crear, suspender y eliminar tenants
- Asignar plan/tier (features habilitados por tenant)
- Ver estado de integraciones por tenant (conectado/desconectado, última actividad)
- Billing y consumo por tenant

#### Integraciones — responsabilidades de plataforma vs tenant

| Integración | Responsabilidad Plataforma | Responsabilidad Tenant |
|---|---|---|
| **WhatsApp** | Registrar Meta App, gestionar `META_APP_SECRET` y `META_VERIFY_TOKEN` en Render. En el futuro: BSP con Embedded Signup. | Configurar WABA ID, Phone Number ID y Access Token desde `/integrations` |
| **Mercado Libre** | Registrar App en MeLi DevCenter, gestionar `MELI_CLIENT_ID` y `MELI_CLIENT_SECRET` en Render. Ver vencimiento de tokens por tenant (6 meses). | Conectar su cuenta vendedor vía OAuth desde `/integrations` |
| **Envia** | Sin responsabilidad de plataforma hoy. Futuro: cuenta partner/reseller Envia. | Configurar su propia API key desde `/integrations` |
| **Telegram** | Sin responsabilidad de plataforma. | Configurar su Bot Token y Chat ID desde `/integrations` |

#### Gestión de credenciales de plataforma (no de tenants)
- Rotar `META_APP_SECRET` cuando Meta lo requiera
- Rotar `MELI_CLIENT_SECRET` cuando venza o se comprometa
- `META_VERIFY_TOKEN` — token de verificación del webhook WhatsApp
- Futuros: Stripe (billing), Resend (SMTP), otros servicios de plataforma

#### Alertas operativas de plataforma
- Tokens MeLi próximos a vencer (tenant no reconectó en +5 meses)
- Tenants con WhatsApp desconectado hace N días
- Errores recurrentes en webhooks por tenant

#### Arquitectura recomendada para Platform Console (cuando se decida OQ-P01)
- **Opción A** (recomendada): misma app Next.js en ruta `/platform/*` con layout y auth separados. Auth de plataforma con tabla `platform_users` propia (no `tenant_users`). RLS con `platform_user_id` en lugar de `tenant_id`.
- **Opción B**: app Next.js completamente separada (`platform.commerce-ops.com`). Más aislamiento, más infraestructura.

---

## Infraestructura activa

| Servicio | URL | Estado |
|---|---|---|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background worker, /health interno) | ✅ Live, polling 3s |

- **Supabase**: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)
- **Tenant dev**: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **WABA ID del tenant dev**: configurado en `tenant_integrations` (provider: `whatsapp`) — ya no en HANDOFF

### Env vars por servicio (estado actual)

| Servicio | Env vars de integración |
|---|---|
| `commerce-ops-connector` | `META_APP_SECRET`, `META_VERIFY_TOKEN` ← solo plataforma |
| `commerce-ops-api` | `MELI_CLIENT_ID`, `MELI_CLIENT_SECRET`, `MELI_REDIRECT_URI`, `MELI_AUTH_URL` |
| `commerce-ops-web` | `MELI_CLIENT_ID`, `MELI_REDIRECT_URI`, `MELI_AUTH_URL` |
| `commerce-ops-orchestrator` | sin vars de integración — lee de DB por tenant |

> `META_ACCESS_TOKEN` y `WHATSAPP_PHONE_ID` fueron **eliminados** de todos los servicios. Las credenciales WhatsApp viven en `tenant_integrations` por tenant.

Para ejecutar SQL:
```bash
supabase db query --linked -f supabase/migrations/archivo.sql
# psql directo NO funciona (Supavisor bloquea TCP)
```

---

## Credenciales activas

| Token | Estado |
|---|---|
| WhatsApp `META_ACCESS_TOKEN` | ✅ Permanente — System User, sin expiración. Almacenado en `tenant_integrations` (provider: `whatsapp`), **no en env vars**. Configurable desde `/dashboard/integrations`. |
| `GEMINI_API_KEY` | ✅ Configurada, billing activo |
| `SUPABASE_JWT_SECRET` | ✅ Presente |

---

## Configuración de App Mercado Libre (Plataforma — se hace UNA vez)

La plataforma usa una sola App MeLi registrada en DevCenter. Cada tenant autoriza su cuenta vendedor a través de OAuth usando esta app. Los tenants **nunca** tocan DevCenter.

### Cómo recrear la app si es necesario

1. Ir a [https://developers.mercadolibre.com.co/devcenter](https://developers.mercadolibre.com.co/devcenter) → **Crear nueva aplicación**

2. **Información básica**
   - Nombre, nombre corto, descripción del negocio
   - Propósito: `Negocios`
   - Usuarios estimados: `1 a 10` (ajustar según escala)
   - Logo de la plataforma

3. **Configuración y scopes**
   - Redirect URI: `https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback`
   - Flujos OAuth: `Authorization Code`, `Client Credentials`, `Refresh Token`
   - PKCE: vacío
   - Unidad de negocio: `Mercado Libre` (no VIS)
   - Permisos:
     - Usuarios: **Lectura y escritura**
     - Publicación y sincronización: **Lectura y escritura**
     - Venta y envíos: **Lectura y escritura**
     - Métricas del negocio: **Lectura**
     - Resto: Sin acceso
   - Tópicos de notificación:
     - `orders_v2` (órdenes nuevas → módulo Pedidos)
     - `items` (cambios en listings)
     - `shipments` (actualizaciones de envío)
   - Callback URL notificaciones: `https://commerce-ops-api.onrender.com/api/v1/meli/webhook`
   - Aceptar Términos y Condiciones

4. **Obtener credenciales** → `App ID` y `Client Secret`

5. **Configurar en Render** (servicios `commerce-ops-web` y `commerce-ops-api`):
   - `MELI_CLIENT_ID` = App ID
   - `MELI_CLIENT_SECRET` = Client Secret
   - `MELI_REDIRECT_URI` = `https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback`
   - `MELI_AUTH_URL` = `https://auth.mercadolibre.com.co/authorization`

---

## Trabajo de la última sesión (2026-04-17) — rev. 22

### Fase 11.6 — Integraciones modulares por tenant + Realtime Inbox + UX

#### Arquitectura de integraciones — modelo final

Cada integración es **completamente por tenant**. La plataforma no tiene credenciales de canal de ningún tenant. La separación es:

- **Plataforma** → registra apps en proveedores externos (Meta DevCenter, MeLi DevCenter), gestiona env vars de plataforma (`META_APP_SECRET`, `META_VERIFY_TOKEN`, `MELI_CLIENT_ID`, `MELI_CLIENT_SECRET`)
- **Tenant** → conecta sus propias cuentas desde `/dashboard/integrations`. Credenciales en `tenant_integrations` por `tenant_id`, aisladas por RLS.

#### WhatsApp — credenciales movidas a DB por tenant

| Área | Cambio | Archivos |
|---|---|---|
| Arquitectura | `META_ACCESS_TOKEN` y `WHATSAPP_PHONE_ID` eliminados de todos los servicios Render | Render env vars |
| Arquitectura | Conector solo necesita `META_APP_SECRET` + `META_VERIFY_TOKEN` — nunca envía mensajes | — |
| Backend | `whatsapp_sender.py` (api + orchestrator): lee `phone_number_id` + `access_token` desde `tenant_integrations` por `tenant_id`. Fallback a env vars solo si tenant no tiene registro en DB. | `services/api/integrations/whatsapp_sender.py`, `services/ai-orchestrator/whatsapp_sender.py` |
| Backend | Disconnect explícito bloquea envíos — `status='disconnected'` ≠ "no configurado". El fallback a env vars solo aplica si nunca se configuró. | ambos `whatsapp_sender.py` |
| Backend | `conversations.py`: pasa `tenant_id` + `supabase` al sender | `services/api/routers/conversations.py` |
| UI | WhatsApp movido de `General` → `Integraciones` como sección "Canal Principal" | `integrations/page.tsx`, `settings/page.tsx` |
| UI | `tenants.meta_waba_id` sigue siendo la clave de routing del conector — se actualiza al guardar/desconectar WhatsApp desde Integraciones | `integrations/page.tsx` |
| UI | Instructivo inline WhatsApp: 4 pasos para obtener WABA ID, Phone Number ID y System User token desde Meta for Developers | `integrations/page.tsx` |
| DB | `meta_waba_id` removido del form y resumen de `/settings`. Solo se muestra en Integraciones. | `settings/page.tsx` |

#### MeLi — documentación y UX

| Área | Cambio | Archivos |
|---|---|---|
| Documentación | App MeLi en DevCenter documentada en HANDOFF (scopes, tópicos, URLs, credenciales) | `docs/HANDOFF.md` |
| UX | Instructivo MeLi mejorado con datos reales: OAuth flow, cuenta principal requerida, vigencia 6 meses, error frecuente | `integrations/page.tsx` |
| Clarificación | El tenant NO toca DevCenter — solo clic OAuth. DevCenter es configuración de plataforma (una vez). | — |

#### Telegram — confirmado live

| Área | Detalle |
|---|---|
| Estado | Integración Telegram ya existía y funciona. Documentada en tree y estado. |
| Funcionalidad | Bot Token + Chat ID por tenant en `notification_settings`. Instructivo 4 pasos inline. Test desde UI lee token de DB (no expone en HTML). |

#### Integraciones page — 4 secciones

| Sección | Integración | Tipo |
|---|---|---|
| Canal Principal | WhatsApp | Manual (WABA ID + Phone ID + Token) |
| Logística | Envia | Manual (API Key) |
| Marketplace | Mercado Libre | OAuth (clic en botón) |
| Notificaciones | Telegram | Manual (Bot Token + Chat ID) |

Contador de conectados: 3 → 4.

#### Inbox — UX y Realtime

| Área | Cambio | Archivos |
|---|---|---|
| UX | Si WhatsApp no está conectado → card centrada "no conectado" (mismo patrón que MeLi en Marketplace). No muestra el inbox. | `inbox/page.tsx` |
| Realtime | Migración `20260417000000`: habilita `postgres_changes` para `conversations` y `messages` en publicación `supabase_realtime`. Sin esto los mensajes no aparecían sin refrescar. | migración aplicada |
| Timeout | Send message: 60s → 90s. Error distingue cold start de error de red real. | `inbox/page.tsx` |

---

## Trabajo de la última sesión (2026-04-15) — rev. 21

### Vuelta 8 — Flujo Invite Validado + UX Polish

| Área | Cambio | Archivos |
|---|---|---|
| Auth | Hash leído ANTES de `createClient()` — evita borrado por `detectSessionInUrl` | `auth/confirm/page.tsx` |
| Auth | Implicit flow usa `setSession({access_token, refresh_token})` explícito — sin race condition | `auth/confirm/page.tsx` |
| Auth | **Flujo completo validado en Render con usuario real** — invite → email → setSession → /set-password → dashboard | — |
| UX Sidebar | `ROLE_BADGE`: emojis 👑🛠️🎧 → Crown/Briefcase/Headphones. Labels: Administrador/Supervisor/Gestor | `sidebar-client.tsx` |
| UX General | `max-w-5xl` removido, `🎨` → Palette icon | `settings/page.tsx` |
| UX Integrations | `max-w-5xl` removido, grid 2×2 (Envia\|MeLi / Telegram\|Próximamente), `🔜` → Clock | `integrations/page.tsx` |
| UX Shipping | `📦📍📐` → Package/MapPin/Box icons, title prop cambiado a ReactNode | `shipping-quote-form.tsx` |
| UX Inventory | `⚙️` → SlidersHorizontal icon | `inventory-manager.tsx` |

### Vuelta 7 — Configuración Certificada + Fix Flujo Invite

| Área | Cambio | Archivos |
|---|---|---|
| Auth | `/auth/confirm/route.ts` eliminado — no puede leer `#access_token=` (fragment) | `auth/confirm/route.ts` (deleted) |
| Auth | `/auth/confirm/page.tsx` Client Component — createBrowserClient lee hash automáticamente | `auth/confirm/page.tsx` |
| Auth | Site URL Supabase → `https://commerce-ops-web.onrender.com` (era localhost:3000) | Supabase Dashboard |
| Roles DB | Migración `20260415030000`: `agent→operator` en `tenant_users` + `add_member_to_tenant` | migración aplicada |
| Roles Frontend | 14 archivos: `?? 'agent'` → `?? 'operator'`, sidebar: entrada 'agent' eliminada | múltiples |
| Seguridad | `changeRole`: guard validación rol, `.neq('role','owner')`, `admin.signOut(userId,'global')` | `team/page.tsx` |
| UX General | Campos obligatorios con `*`, celular `+57` fijo, `pattern="3[0-9]{9}"`, NIT opcional | `settings/page.tsx` |
| UX General | País bloqueado a Colombia, select dpto→municipio DANE sin buscador libre | `shipping-origin-form.tsx` |
| UX Integraciones | 3 secciones (Logística/Marketplace/Notificaciones), instructivos inline, íconos Lucide | `integrations/page.tsx` |
| UX Equipo | Bot Token y Chat ID: `type=text` con placeholder ejemplo real | `integrations/page.tsx` |
| UX Equipo | Banner azul info tras cambio de rol (forzar re-login) | `team/page.tsx` |

### Vuelta 6 — Cierre Dominio Configuración + Hardening Seguridad

| Área | Cambio | Archivos |
|---|---|---|
| Seguridad | RLS activado en `tenant_users` + unique constraint | migración `20260415000000` |
| Seguridad | Función `add_member_to_tenant` (SECURITY DEFINER) | migración `20260415000000` |
| Seguridad | `logo-upload.tsx`: `getSession()` → `getUser()` | `settings/logo-upload.tsx` |
| Seguridad | Security Headers (CSP, HSTS, X-Frame-Options, etc.) | `apps/web/next.config.js` |
| General | `low_stock_threshold` editable en UI (validación 1–999) | `settings/page.tsx` |
| Usuarios y Acceso | Invite por email con `adminClient` (flujo completo) | `team/page.tsx` |
| Infraestructura | `utils/supabase/admin.ts` — cliente Service Role para SSR | nuevo archivo |

---

## Intervenciones Humanas Pendientes

### ~~IH-001~~ ✅ RESUELTA — Supabase Site URL + Redirect URLs
`NEXT_PUBLIC_APP_URL` configurado en Render. Site URL cambiado a `https://commerce-ops-web.onrender.com`. Redirect URLs incluyen `/auth/confirm` y `/set-password`.

### IH-002 — ALLOWED_ORIGINS en FastAPI

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | DevOps / Owner del proyecto |
| **PASOS** | 1. Render → Service `commerce-ops-api` → Environment <br> 2. `ALLOWED_ORIGINS=https://commerce-ops-web.onrender.com,http://localhost:3000` <br> 3. Redeploy del servicio api |
| **INSUMOS** | URL: `https://commerce-ops-web.onrender.com` |
| **CRITERIO DE ÉXITO** | No aparecen errores CORS en producción |

### ~~IH-INVITE-VALIDATE~~ ✅ RESUELTA — 2026-04-15
Validado con `crittan01@gmail.com` en Render. Flujo completo: invite → email → `/auth/confirm#access_token=` → `setSession()` → `/set-password` → dashboard. Fix clave: hash capturado antes de `createClient()` + `setSession()` explícito.

### IH-SMTP — SMTP custom con Resend (requiere dominio propio)

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | Arquitecto técnico |
| **CUANDO** | Al tener dominio propio verificado |
| **PASOS** | 1. Resend.com → Domains → verificar dominio <br> 2. Resend → API Keys → `Sending access` <br> 3. Supabase → Auth → SMTP → Enable Custom SMTP <br> 4. Host: `smtp.resend.com` \| Port: `465` \| User: `resend` \| Password: API Key <br> 5. Sender: `noreply@tudominio.com` |
| **NOTA** | Gmail como sender falla DMARC `p=reject` — no usar @gmail.com como sender |
| **CRITERIO DE ÉXITO** | Invitación llega en <1 minuto sin rate limit |

---

## Deuda técnica activa

| Ítem | Prioridad |
|---|---|
| IH-SMTP — SMTP custom con Resend (requiere dominio propio; Gmail bloqueado por DMARC p=reject) | Media — rate limit 3/hora en Free. No bloquea operación actual. |
| Envia Fase 2: label, tracking, pickup | Media |
| Sync catálogo completo MeLi (precios/descripciones MeLi→Supabase automático) | Media |
| IH-002: `ALLOWED_ORIGINS` en FastAPI (CORS producción) | Media — intervención humana |

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

---

## Referencias rápidas

| Archivo | Contenido |
|---|---|
| `.context/00-product.md` | Tree funcional vigente — leer primero |
| `.context/01-state.md` | Estado de implementación real |
| `.context/04-next-steps.md` | Próximos pasos, IH pendientes y deuda |
| `.context/05-doc-policy.md` | Política documental |
| `docs/architecture/settings-domain.md` | Técnico completo del dominio Configuración |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño Shipping/Courier |
| `docs/risks/open-questions.md` | Preguntas abiertas — OQ-P01 |
| `docs/roadmap/implementation-phases.md` | Fases 1-13 con estado |

---

## Lecciones críticas (no repetir)

1. `google-generativeai` deprecated → usar `google-genai==1.47.0`
2. `NODE_ENV=production` + `npm install` omite devDeps → `--include=dev`
3. `apps/web` requiere `postcss.config.js` + `autoprefixer` en devDeps para Tailwind en Render
4. `psql` TCP bloqueado por Supavisor → `supabase db query --linked`
5. `getSession()` en Server Components es inseguro → siempre `getUser()` (aplica también en Client Components)
6. Funciones arrow `() => {}` como props RSC no son serializables → props opcionales con default interno
7. ESLint v10 incompatible con Next.js 14 → `eslint@8`
8. `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
9. Si CSS se ve plano en Render → "Clear build cache & deploy"
10. Trigger `tenant_users`: usar `NEW.user_id`, no `NEW.id`
11. `adminClient` (Service Role) bypasea RLS — usar solo en Server Actions con guard de rol explícito antes de llamarlo
12. `inviteUserByEmail` requiere `NEXT_PUBLIC_APP_URL` configurada en Render para que el `redirectTo` del email apunte al dominio correcto
13. `inviteUserByEmail` usa **implicit flow** → sesión en `#access_token=` (URL fragment). Los Route Handlers nunca reciben el fragment — usar Client Component
14. Tras cambio de rol: JWT activo retiene claims hasta 1 hora — invalidar con `admin.signOut(userId, 'global')` para forzar re-login
15. Gmail como SMTP sender falla DMARC `p=reject` — usar dominio propio con Resend cuando disponible
16. `createBrowserClient` con `detectSessionInUrl: true` dispara `SIGNED_IN` async
17. El conector WhatsApp **nunca** necesita `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` — solo recibe webhooks. Esas vars son del sender (api + orchestrator) y ahora viven en DB por tenant.
18. Fallback de credenciales en senders: distinguir `status='disconnected'` (bloquear envío) de "sin registro" (permitir fallback a env vars durante migración). Son estados diferentes.
19. Supabase Realtime requiere `ALTER PUBLICATION supabase_realtime ADD TABLE` explícito — las tablas nuevas NO se agregan automáticamente. Sin esto, `postgres_changes` no emite eventos aunque el canal esté suscrito.
20. MeLi token de acceso expira cada 6 horas pero el refresh token dura 6 meses. La plataforma renueva automáticamente. A los 6 meses el tenant debe reconectar desde Integraciones.
21. El tenant de MeLi NUNCA crea una app en DevCenter — eso es responsabilidad de plataforma. El tenant solo autoriza su cuenta vendedor via OAuth con la app de la plataforma. (`setTimeout(0)`) y puede borrar el hash via `history.replaceState`. Solución probada: leer `window.location.hash` **antes** de `createClient()`, luego usar `supabase.auth.setSession({access_token, refresh_token})` explícito — patrón recomendado en supabase/discussions#21097
