# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

## Contexto documental vigente (actualizado 2026-04-10, rev. 16 — UI Plus Total + nav reestructurada)

La documentación del repositorio fue auditada, corregida y actualizada para reflejar el estado real del código.
Archivos clave del producto y arquitectura existen y están alineados:
- `docs/product/` — product overview, scope, current-scope, personas-and-consoles, admin-ui-modules, navigation-map
- `docs/architecture/front-back-separation.md` — mapeo Frontend ↔ Backend + BLOQUEs alineados
- `docs/architecture/nav-architecture.md` — **[NUEVO]** Mapa de navegación oficial, grupos, RBAC, reglas de sidebar
- `docs/integrations/courier-envia.md` — Fase Inicial implementada (envia_client.py, shipping.py, /dashboard/shipping)
- `docs/roadmap/implementation-phases.md` — Fases 1-11 completadas, 12-13 pendientes
- `CLAUDE.md` — **[NUEVO]** Contexto completo para Claude Code (stack, nav, reglas, comandos)

### ESTRUCTURA DE FASES — estado real 2026-04-10 (rev. 16)

| Fase | Nombre | Estado |
|------|--------|--------|
| 1-6 | Base, Auth, UI, WhatsApp, AI, API Gateway | ✅ COMPLETADAS |
| 7 | Deploy Render + E2E | ✅ COMPLETADA — WhatsApp↔Gemini↔Inbox confirmado |
| 8 | Catálogo completo + RBAC base | ✅ COMPLETADA 2026-04-09 |
| 9 | Schema core + Pedidos + Configuración + Equipo | ✅ COMPLETADA 2026-04-09 |
| 10 | Integraciones: MeLi + Envia/Shipping | ✅ COMPLETADA 2026-04-09 |
| 11 | Módulos restantes Tenant Console | ✅ COMPLETADA 2026-04-09 |
| 11.1 | UI "Plus Total" — 13 módulos Enterprise SaaS responsive | ✅ COMPLETADA 2026-04-10 — commit 6a496c7 |
| 11.2 | Nav reestructurada — grupos expandibles, RBAC dual, labels corregidos | ✅ COMPLETADA 2026-04-10 |
| 12 | Platform Console | ❌ PENDIENTE — OQ-P01 bloqueante |
| 13 | Shopify / Tienda custom | ❌ FUTURO |

Ver `docs/HANDOFF.md` para estado completo y próximos pasos.

---

## Estado Actual del Sistema

> Estado detallado por módulo → `docs/product/current-scope.md`
> Servicios live, infraestructura, credenciales → `docs/HANDOFF.md`

**Resumen**: Fases 1-11.2 ✅ completadas. Tenant Console 13/13 módulos live con UI Enterprise. Nav reestructurada con grupos expandibles. Fase 12 ❌ pendiente (bloqueante: OQ-P01).

**Credenciales activas (`.env` — nunca al repo):**
- `META_ACCESS_TOKEN`: ✅ Token permanente — System User `commerce-ops` (IH-006)
- `GEMINI_API_KEY`: ✅ Configurada — billing activo (paid tier)
- `SUPABASE_JWT_SECRET`: ✅ Presente
- `GEMINI_MODEL`: `gemini-2.5-flash` — único modelo activo en cuentas nuevas con billing

> **Nota CSS (lección aprendida)**: `apps/web` requiere `postcss.config.js` + `autoprefixer` en devDeps.
> `NODE_ENV=production` hace que `npm install` omita devDeps → solución: `--include=dev` en buildCommand.
> Si el CSS se ve plano: **"Clear build cache & deploy"** en Render Dashboard (Next.js cachea transformaciones CSS).

**Herramientas instaladas en VM (sin venv — máquina dedicada) — verificado 2026-04-10:**
- `supabase` CLI v2.84.2 → `supabase db query --linked -f archivo.sql`
- `psql` 15.17 via DNF (TCP bloqueado por Supavisor — usar CLI `--linked`)
- Python **3.11.13** (Oracle Linux 9, instalado vía dnf) — sin venv, paquetes en sistema. `Optional[X]` sigue siendo el estilo usado en el código.
- Node v20.20.2 via nvm, pnpm 10.33.0
- `pip3` sistema — paquetes alineados con requirements.txt:
  ```
  google-genai==1.47.0       ← SDK oficial (google-generativeai deprecado: DESINSTALADO)
  supabase==2.28.3
  httpx==0.28.1
  pydantic==2.12.5
  PyJWT==2.10.1
  fastapi==0.128.8
  uvicorn==0.39.0
  python-dotenv==1.2.1
  python-multipart==0.0.20
  anyio==4.12.1
  starlette==0.49.3
  ```

## Hardening completado (2026-04-10)

- `getSession()` → `getUser()` en todos los Server Components (seguridad JWT)
- Next.js `14.1.0` → `14.2.35` (CVE crítico + 6 high parcheados)
- Error boundaries: `app/error.tsx` + `app/dashboard/error.tsx`
- AbortController (15-20s) en fetch() de orders, inbox, shipping
- ESLint `^10` → `8.x` + `.eslintrc.json` con `next/core-web-vitals`
- Fix RSC: props `onCreated/onQuoted/onSaved` movidos a defaults internos (Catálogo, Pedidos, Envíos, Config)
- 13 migraciones aplicadas: `tenants.low_stock_threshold` + `contacts.consent_given/consent_date`

## Próximo a Implementar

**Fase 12 — Platform Console** — prerrequisito: OQ-P01 decidido

Pasos antes de comenzar:
1. Decidir OQ-P01: ¿misma app Next.js (`/platform/*`) vs app separada?
2. Diseñar tabla `platform_users` con roles `platform_superadmin`, `platform_support`, `platform_ops`
3. Definir lógica de auth diferenciada en `middleware.ts` para rutas `/platform/*`
4. Definir endpoints platform-only en `services/api`

Ver detalle completo en `docs/roadmap/implementation-phases.md` — Fase 12.

---

**Para activar el Orchestrator hoy (local):**
```bash
# 1. Agregar GEMINI_API_KEY al .env
# 2. Ejecutar:
cd /home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py
```

Ver guía completa: `docs/deployment/DEPLOYMENT_GUIDE.md`  
Ver estado de infraestructura: `docs/architecture/modules.md`  
Ver intervenciones humanas: `docs/operations/HUMAN_INTERVENTIONS.md`

## Reglas Obligatorias para AI Agents

1. **Documentación Oficial**: No asumas endpoints, scopes ni capacidades. Valida en docs oficiales siempre.
2. **Políticas de Meta**: Todo diseño conforme a WhatsApp Cloud API Anti-Spam y políticas de mensaje.
3. **No Magia LLM**: El LLM nunca es fuente de verdad para stock, precios, pedidos, permisos ni estados.
4. **Multi-Tenant Real**: Cada operación debe estar atada a `tenant_id` y filtrada por RLS en Postgres.
5. **No MVP / Demo**: Diseñar para producción real. No atajos de seguridad ni hardcodes de tenant.
6. **Seguridad en capas**: RLS es la última barrera. El API Gateway es la barrera previa. El frontend no es seguridad.
7. **Verificar skills y MCP** antes de asumir que están habilitados.

## Leer Antes de Tocar Código

- `CLAUDE.md` — **Contexto rápido para Claude Code** (stack, nav, reglas, comandos)
- `.agents/rules/` — Reglas técnicas expandidas (incluye `nav-architecture.md`)
- `.agents/workflows/` — Workflows de implementación, feature, seguridad
- `docs/product/current-scope.md` — Estado real de implementación hoy
- `docs/product/admin-ui-modules.md` — Módulos de ambas consolas con estado
- `docs/architecture/nav-architecture.md` — Mapa oficial de navegación, grupos, RBAC
- `docs/architecture/modules.md` — Responsabilidades de cada módulo backend
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend
- `docs/architecture/multi-tenant-security.md` — Contratos de RLS
- `docs/integrations/courier-envia.md` — Diseño de Shipping/Courier

## Stack — Versiones Reales en Repo

> Verificado en `apps/web/package.json` y `services/*/requirements.txt`.

| Capa | Versión real | Objetivo futuro |
|---|---|---|
| Frontend | Next.js **14.2.35** + React ^18 + TypeScript ^5 | Next.js 15.x |
| UI | TailwindCSS ^3.3.0 + shadcn/ui (5 componentes en `apps/web/components/ui/`) | Componentes en `packages/ui` |
| Backend | Python **3.11.13** (VM) + FastAPI 0.128.8 | — |
| DB / Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) | — |
| IA | Google Gemini API (`google-genai==1.47.0`, modelo `gemini-2.5-flash`) | — |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) | — |
| Shipping | Envia (🟡 Fase Inicial — quote + historial operativos) | Label/tracking: Fase 2 |
| Hosting | Render (Web Services + Background Workers) — Free plan | Starter antes de producción |

> `packages/ui` está vacío. Los componentes UI viven en `apps/web/components/ui/`.
> No asumir versiones de las docs — verificar siempre en `package.json` y `requirements.txt`.

## Crítico — Seguridad Git

- `.env` **NUNCA** va al repositorio. Config en Render Environment Variables.
- `node_modules/`, `.venv/`, `.next/` están en `.gitignore`.
