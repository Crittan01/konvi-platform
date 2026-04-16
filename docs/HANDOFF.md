# Handoff — Estado del Proyecto al 2026-04-15 (rev. 20)

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
| DB / Auth | Supabase — 22 migraciones aplicadas, RLS + JWT Claims |
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

---

## Tenant Console — Estado de módulos

Ver tabla completa → `.context/01-state.md`

Resumen: 18 módulos live. Configuración certificada con 2 pendientes: validar invite flow en Render + SMTP propio cuando haya dominio.

---

## Platform Console

**Estado**: ❌ No existe. Cero rutas, cero layout, cero auth de plataforma.
**Prerrequisito bloqueante**: OQ-P01 — ¿misma app Next.js (`/platform/*`) vs app separada?
**No se toca en la iniciativa actual.** Solo aparece como frontera futura.

---

## Infraestructura activa

| Servicio | URL | Estado |
|---|---|---|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background worker, /health interno) | ✅ Live, polling 3s |

- **Supabase**: `xmelwnhhphksbpdjmbbp` (us-east-1)
- **Tenant dev**: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **meta_waba_id**: `2159052118202272`

Para ejecutar SQL:
```bash
supabase db query --linked -f supabase/migrations/archivo.sql
# psql directo NO funciona (Supavisor bloquea TCP)
```

---

## Credenciales activas

| Token | Estado |
|---|---|
| `META_ACCESS_TOKEN` | ✅ Permanente — System User `commerce-ops`, sin expiración |
| `GEMINI_API_KEY` | ✅ Configurada, billing activo |
| `SUPABASE_JWT_SECRET` | ✅ Presente |

---

## Trabajo de la última sesión (2026-04-15) — rev. 20

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

### IH-INVITE-VALIDATE — Validar flujo completo de invitación en Render

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | Arquitecto técnico |
| **PASOS** | 1. `/dashboard/team` → invitar nuevo email <br> 2. Abrir email → clic en enlace (apunta a Render) <br> 3. `/auth/confirm#access_token=...` carga — Client Component lee hash <br> 4. Redirige a `/set-password` → usuario crea contraseña <br> 5. Accede a `/dashboard` |
| **CRITERIO DE ÉXITO** | Flujo completo sin "Enlace inválido" ni redirección a localhost |

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
| IH-INVITE-VALIDATE — Confirmar flujo invite en Render | **Alta** — pendiente de ejecución |
| IH-SMTP — SMTP custom con Resend (requiere dominio propio; Gmail bloqueado por DMARC) | Alta — rate limit 3/hora en Free |
| Envia Fase 2: label, tracking, pickup | Media |
| Sync bidireccional catálogo ↔ MeLi listings | Media |
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
13. `inviteUserByEmail` usa **implicit flow** → sesión en `#access_token=` (URL fragment). Los Route Handlers (server) nunca reciben el fragment — usar Client Component con `createBrowserClient` que tiene `detectSessionInUrl: true`
14. Tras cambio de rol: el JWT activo retiene claims viejos hasta 1 hora — invalidar con `admin.signOut(userId, 'global')` para forzar re-login inmediato
15. Gmail como SMTP sender falla DMARC `p=reject` — usar dominio propio con Resend cuando disponible
