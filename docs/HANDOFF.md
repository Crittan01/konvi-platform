# Handoff — Estado del Proyecto al 2026-04-15 (rev. 18)

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
| DB / Auth | Supabase — 20 migraciones aplicadas, RLS + JWT Claims |
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

Resumen: 18 módulos live. Configuración completamente cerrada (General, Usuarios y Acceso, Integraciones).

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

## Trabajo de la última sesión (2026-04-15) — rev. 18

### Cierre Dominio Configuración + Hardening de Seguridad

| Área | Cambio | Archivos |
|---|---|---|
| Seguridad | RLS activado en `tenant_users` + unique constraint | migración `20260415000000` |
| Seguridad | Función `add_member_to_tenant` (SECURITY DEFINER) | migración `20260415000000` |
| Seguridad | `logo-upload.tsx`: `getSession()` → `getUser()` | `settings/logo-upload.tsx` |
| Seguridad | Security Headers (CSP, HSTS, X-Frame-Options, etc.) | `apps/web/next.config.js` |
| General | `low_stock_threshold` editable en UI (validación 1–999) | `settings/page.tsx` |
| General | `revalidatePath('/dashboard')` al guardar threshold | `settings/page.tsx` |
| Usuarios y Acceso | Invite por email con `adminClient` (flujo completo) | `team/page.tsx` |
| Usuarios y Acceso | Banners de resultado en UI | `team/page.tsx` |
| Infraestructura | `utils/supabase/admin.ts` — cliente Service Role para SSR | nuevo archivo |
| Documentación | `docs/architecture/settings-domain.md` | nuevo archivo |
| Documentación | `.context/` y `HANDOFF.md` actualizados | múltiples |

---

## Intervenciones Humanas Pendientes

### IH-001 — Variables de entorno para invite de miembros (Render)

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | DevOps / Owner del proyecto |
| **PASOS** | 1. Render Dashboard → Service `commerce-ops-web` → Environment <br> 2. Agregar `NEXT_PUBLIC_APP_URL=https://commerce-ops-web.onrender.com` <br> 3. Verificar que `SUPABASE_SERVICE_ROLE_KEY` esté configurado (no `NEXT_PUBLIC_`) <br> 4. Redeploy del servicio web |
| **INSUMOS** | URL: `https://commerce-ops-web.onrender.com` · Service Role Key: Supabase Dashboard → Project Settings → API |
| **CRITERIO DE ÉXITO** | Al invitar desde `/dashboard/team`, el email llega con enlace `https://commerce-ops-web.onrender.com/auth/confirm?token=...` |

### IH-002 — ALLOWED_ORIGINS en FastAPI

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | DevOps / Owner del proyecto |
| **PASOS** | 1. Render → Service `commerce-ops-api` → Environment <br> 2. `ALLOWED_ORIGINS=https://commerce-ops-web.onrender.com,http://localhost:3000` <br> 3. Redeploy del servicio api |
| **INSUMOS** | URL: `https://commerce-ops-web.onrender.com` |
| **CRITERIO DE ÉXITO** | No aparecen errores CORS en producción (`Access-Control-Allow-Origin` presente en responses de la API) |

---

## Deuda técnica activa

| Ítem | Prioridad |
|---|---|
| Reclamos — `resolution_notes` editables (Server Action faltante) | Alta |
| Envia Fase 2: label, tracking, pickup | Media |
| Sync bidireccional catálogo ↔ MeLi listings | Media |
| **IH-003: SMTP propio en Supabase** — Free tier tiene rate limit ~4 emails/hora. Sin SMTP propio el invite/resend falla en uso real. Usar Resend.com (gratis 3k/mes) o Gmail App Password. `Supabase Dashboard → Auth → Settings → SMTP` | **Alta** — bloquea invitaciones |
| IH-002: `ALLOWED_ORIGINS` en FastAPI (CORS producción) | Media — intervención humana |
| Reglas de Negocio — definir caso de uso antes de implementar | Baja |

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
