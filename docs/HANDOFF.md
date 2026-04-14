# Handoff — Estado del Proyecto al 2026-04-14 (rev. 17)

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

Resumen: 17 módulos live. Reclamos en estado parcial (stub + tabla DB, acciones pendientes).

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

- **Supabase**: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)
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

## Trabajo de la última sesión (2026-04-14) — rev. 17

### Reestructuración Arquitectónica y Documental

| Cambio | Detalle |
|---|---|
| Route Groups implantados | `(sales)`, `(products)`, `(channels)`, `(ai)`, `(analytics)`, `(settings-group)` |
| Single Source of Truth consolidado | `.context/00-product.md` reescrito con tree funcional aprobado |
| `.context/01-state.md` reescrito | Refs rotas eliminadas, estado actualizado, 20 migraciones documentadas |
| `.context/05-doc-policy.md` creado | Política documental explícita — jerarquía y reglas de consistencia |
| `AGENTS.md` reescrito | Sin duplicados con `.context/`, referencia clara a fuentes |
| `CLAUDE.md` reescrito | Limpio, sin duplicados, lecciones al final |
| `README.md` actualizado | Python corregido (3.9.25→3.11.13), refs actualizadas |
| Stubs vacíos eliminados | `docs/product/functional-requirements.md`, `non-functional-requirements.md`, `docs/architecture/async-processing.md`, `output-template.md`, `realtime.md` |
| Scripts debug movidos | `find_leaf*.py`, `test_*.py`, `meli_sandbox.py`, `decode_jwt_header.py` → `scripts/debug/` |
| Linting hardening | Prettier + ESLint fuerte + Ruff (`pyproject.toml`) |

---

## Deuda técnica activa

| Ítem | Prioridad |
|---|---|
| Reclamos — acciones reales (crear, cambiar estado, vincular pedido) | Alta |
| Agentes IA — desbloquear en sidebar (`locked: true` → quitar) | Alta |
| Dashboard — `tenants.low_stock_threshold` dinámico (eliminar hardcode `<= 5`) | Media |
| Dashboard KPIs — eliminar trends hardcodeados (`+12%`, `+5%`) | Media |
| Envia Fase 2: label, tracking, pickup | Media |
| Sync bidireccional catálogo ↔ MeLi listings | Media |

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

---

## Referencias rápidas

| Archivo | Contenido |
|---|---|
| `.context/00-product.md` | Tree funcional vigente — leer primero |
| `.context/01-state.md` | Estado de implementación real |
| `.context/04-next-steps.md` | Próximos pasos y deuda |
| `.context/05-doc-policy.md` | Política documental |
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
5. `getSession()` en Server Components es inseguro → siempre `getUser()`
6. Funciones arrow `() => {}` como props RSC no son serializables → props opcionales con default interno
7. ESLint v10 incompatible con Next.js 14 → `eslint@8`
8. `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
9. Si CSS se ve plano en Render → "Clear build cache & deploy"
10. Trigger `tenant_users`: usar `NEW.user_id`, no `NEW.id`
