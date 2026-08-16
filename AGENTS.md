# Workspace AI Guidelines — Konvi Platform

**Leer siempre antes de tocar código o documentación.**

---

## Qué es este producto

SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp (B2B2C, foco Colombia).
El LLM (Gemini) es asistencia controlada — nunca fuente de verdad de datos transaccionales.

## Dónde está la fuente de verdad

| Qué buscar | Dónde |
|---|---|
| Tree funcional, dominios, qué es módulo | `.context/00-product.md` ← **OBLIGATORIO leer primero** |
| Estado de implementación real | `.context/01-state.md` |
| Stack con versiones reales | `.context/02-stack.md` |
| Reglas de implementación | `.context/03-rules.md` |
| Próximos pasos y deuda | `.context/04-next-steps.md` |
| Política documental | `.context/05-doc-policy.md` |
| PRD — qué es el producto | `docs/product/PRD.md` |
| Plan maestro y backlog priorizado | `docs/PLAN.md` |
| TRD — requisitos técnicos | `docs/tech/TRD.md` |
| Backend canónico (servicios, routers, workers) | `docs/backend/BACKEND.md` |
| UX/UI canónica (design system Kaiu) | `docs/ux/UX-UI.md` |
| Flujos end-to-end (compra, pago, envío…) | `docs/flows/` |
| Integraciones (Wompi, Aveonline, Meta, MeLi, Telegram) | `docs/integrations/` |
| Índice de ADRs | `docs/adr/README.md` |
| Infra, credenciales, lecciones | `docs/HANDOFF.md` |
| Arquitectura técnica | `docs/architecture/` |
| Reglas técnicas expandidas | `.agents/rules/` |
| Workflows de implementación | `.agents/workflows/` |

---

## Estado Actual del Sistema

**Fases 1-11.5 ✅ completadas** (incl. Reclamos, Compras, Finanzas, Marketplace). Fase 12 ❌ pendiente (bloqueante: OQ-P01).

Ver estado detallado por módulo → `.context/01-state.md`
Ver servicios live e infra → `docs/HANDOFF.md`

## Reglas Obligatorias para AI Agents

1. **Documentación Oficial**: No asumas endpoints, scopes ni capacidades. Valida en docs oficiales siempre.
2. **Políticas de Meta**: Todo diseño conforme a WhatsApp Cloud API Anti-Spam y políticas de mensaje.
3. **No Magia LLM**: El LLM nunca es fuente de verdad para stock, precios, pedidos, permisos ni estados.
4. **Multi-Tenant Real**: Cada operación debe estar atada a `tenant_id` y filtrada por RLS en Postgres.
5. **No MVP / Demo**: Diseñar para producción real. Sin atajos de seguridad ni hardcodes de tenant.
6. **Seguridad en capas**: RLS es la última barrera. El API Gateway es la barrera previa. El frontend no es seguridad.
7. **Tree primero**: Antes de crear o mover un módulo, leer `.context/00-product.md`.
8. **Platform Console fuera de alcance**: No diseñar, expandir ni implementar Platform Console en esta iniciativa.

---

## Stack — Versiones Reales

> Detalle completo y política de herramientas: **`.context/02-stack.md`** (L2 canónico).
> Verificar siempre en `apps/web/package.json` y `services/*/requirements.txt`. No asumir versiones.

| Capa | Versión real (2026-08-02) |
|---|---|
| Frontend | Next.js **16.2.11** + React ^19 + TypeScript ^5 |
| UI | TailwindCSS **4.3.3** (tokens en `globals.css`) + shadcn/ui — **20 componentes + empty-state + motion** en `apps/web/components/ui/` |
| Backend | Python **3.11** + FastAPI **0.139.0** (api + orchestrator; connector-whatsapp va una minor atrás) |
| DB / Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) — 251 migraciones = ledger prod, 79 tablas live |
| IA | `google-genai==2.11.0` — Gemini 3.x (primario prod `gemini-3.1-flash-lite`) |
| Mensajería | WhatsApp Cloud API (Meta Graph API **v22.0**, Model B per-tenant) |
| Shipping | **Aveonline** (único provider — Envia eliminado del runtime en rev.109) |
| Hosting | Render — Free plan (4 servicios live) — ver upgrade path en `docs/deployment/render-upgrade-path.md` |
| Tests | 4.298 pytest colectados (201 dbharness) + 31 archivos Vitest |

---

## Fases de Implementación

| Fases | Estado |
|---|---|
| 1-11.5 | ✅ Completadas |
| 12 (Platform Console) | ❌ Bloqueada — OQ-P01 sin resolver — fuera de alcance actual |
| 13 (Shopify) | ❌ Futuro lejano |

---

## Herramientas en VM (sin venv)

```bash
supabase db query --linked -f archivo.sql   # psql TCP bloqueado por Supavisor (solo para PROD explícito)
python3.11 main.py                          # usar python3.11 explícito en esta VM
pnpm --filter web dev                       # Node 22 (`.nvmrc`; v22.23.1 instalada via nvm)
```

**Target por defecto del desarrollo local (ENV-1, 2026-08-03):** `.env.local` (raíz, 3 servicios Python) y `apps/web/.env.local` apuntan al **Supabase LOCAL en podman** (`http://127.0.0.1:54321`, DB `:54322`, Studio `:54323`) — no a la nube. Levantar DB: `export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock" && supabase start`. Levantar los 4 servicios: `make -C .local up` (topología **homologada a PRD** desde S7 2026-08-16: env filtrado por servicio = render.yaml, mismos entrypoints; certificar con `bash scripts/certify_stg.sh`). Para operar PROD se usa `.env.prd-backup` explícito (ver `docs/infra/environments.md` §2).

---

## Seguridad Git

- `.env` **NUNCA** al repositorio. Config en Render Environment Variables.
- `node_modules/`, `.venv/`, `.next/` están en `.gitignore`.
- Rama activa: `develop` → `origin/develop`
