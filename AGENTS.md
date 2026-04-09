# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

## Contexto documental vigente (actualizado 2026-04-09, rev. 7 — re-baseline completo)

La documentación del repositorio fue completamente gobernada, auditada y re-baselined.
Archivos clave del producto y arquitectura existen y están alineados:
- `docs/product/` — product overview, scope, current-scope, personas-and-consoles, admin-ui-modules, navigation-map
- `docs/architecture/front-back-separation.md` — mapeo Frontend ↔ Backend + BLOQUEs alineados con nueva estructura de Fases
- `docs/integrations/courier-envia.md` — diseño completo del módulo Shipping/Courier (Envia)
- `docs/roadmap/implementation-phases.md` — re-baselined: Fases 1-13 con nueva estructura
- `docs/roadmap/milestones.md` — actualizado con ajustes de timeline por re-baseline
- Todos los stubs de docs/risks/, docs/research/, docs/operations/ fueron expandidos
- rev. 5: Contradicciones de versiones y estados corregidas
- rev. 6: README reescrito, diagrama de arquitectura corregido, contradicción Fase 9/10 Shipping resuelta
- rev. 7: Re-baseline completo — dependencia invertida MeLi/Orders corregida; roadmap reestructurado
  Fases 8-13; BLOQUEs alineados con Fases; milestones actualizados

### NUEVA ESTRUCTURA DE FASES (rev. 7)

| Fase | Nombre | Estado |
|------|--------|--------|
| 1-6 | Base, Auth, UI, WhatsApp, AI, API Gateway | ✅ COMPLETADAS |
| 7 | Deploy Render + E2E | ✅ COMPLETADA — WhatsApp↔Gemini↔Inbox confirmado |
| 8 | Catálogo completo + RBAC base | ❌ PENDIENTE |
| 9 | Schema core + Pedidos + Configuración + Equipo | ❌ PENDIENTE |
| 10 | Integraciones: MeLi + Envia/Shipping (juntos) | 📋 DISEÑADO |
| 11 | Módulos restantes Tenant Console | ❌ PENDIENTE |
| 12 | Platform Console | ❌ PENDIENTE — OQ-P01 bloqueante |
| 13 | Shopify / Tienda custom | ❌ FUTURO |

> **Cambio clave**: MeLi era Fase 8 antes; ahora es Fase 10 junto con Envia.
> Razón: MeLi necesita `orders` y `tenant_integrations` que no existen — deben crearse en Fase 9 primero.

Ver `docs/HANDOFF.md` para estado completo y próximos pasos.

---

## Estado Actual del Sistema — 2026-04-09T03:30 CDT

| Módulo | Estado | Notas |
|---|---|---|
| Supabase Cloud | ✅ Activo | proyecto `***SUPABASE_PROJECT_REF_REDACTED***` |
| Migraciones SQL (6) | ✅ Todas aplicadas | +`messages.processed` con índice parcial |
| Tenant activo | ✅ Configurado | `Matriz Commerce Dev`, `meta_waba_id=2159052118202272` |
| Frontend Backoffice | ✅ Live en Render | UI con TailwindCSS ✅ — ver nota CSS abajo |
| WhatsApp Connector | ✅ Live en Render | health `/health` OK |
| AI Orchestrator | ✅ Live + polling activo | `gemini-2.5-flash`, billing Google habilitado |
| Inbox AI Dashboard | ✅ Funcional | Realtime, Human Takeover, bubble UI |
| API Gateway (Fase 6) | ✅ Live en Render | JWT real, productos CRUD, conversaciones |
| render.yaml | ✅ v5 | `npm install --include=dev` + `NODE_OPTIONS=460MB` |
| Deploy Render (Fase 7) | ✅ COMPLETADA | E2E confirmado 2026-04-09 — WhatsApp ↔ Gemini ↔ Inbox OK |
| `services/orchestrator/` | ✅ ELIMINADO | Prototipo obsoleto — canónico: `services/ai-orchestrator/` |
| Integración MeLi | ❌ Pendiente | Fase 8 |

**Credenciales activas (`.env` — nunca al repo) — estado 2026-04-09:**
- `META_ACCESS_TOKEN`: ✅ **Token permanente** — System User `commerce-ops` creado en Meta Business Suite (IH-006 ✅ 2026-04-09)
- `GEMINI_API_KEY`: ✅ Configurada — billing habilitado en Google AI Studio (paid tier)
- `SUPABASE_JWT_SECRET`: ✅ Presente
- `meta_waba_id`: `2159052118202272` ✅
- `GEMINI_MODEL`: `gemini-2.5-flash` — único modelo activo en cuentas nuevas con billing

> **Nota CSS (lección aprendida)**: `apps/web` requiere `postcss.config.js` + `autoprefixer` en devDeps.
> `NODE_ENV=production` hace que `npm install` omita devDeps → solución: `--include=dev` en buildCommand.
> Si el CSS se ve plano: **"Clear build cache & deploy"** en Render Dashboard (Next.js cachea transformaciones CSS).

**Herramientas instaladas en VM (sin venv — máquina dedicada) — verificado 2026-04-08:**
- `supabase` CLI v2.84.2 → `supabase db query --linked -f archivo.sql`
- `psql` 15.17 via DNF (TCP bloqueado por Supavisor — usar CLI `--linked`)
- Python 3.9.25 (Oracle Linux 9) — `Optional[X]`, no `X | None`. ⚠️ EOL — Google ya emite FutureWarning
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

## Próximo a Implementar

**Fase 7 — Deploy en Render** — PASOS 1-5 completados ✅
> Ver guía detallada: `docs/deployment/FASE7_RENDER_DEPLOY.md`

Completado ✅:
- 4 servicios live en Render (web + connector + api + orchestrator)
- Smoke tests PASO 5 pasados desde VM
- Gemini billing habilitado + modelo `gemini-2.5-flash`
- TailwindCSS fix: `postcss.config.js` + `--include=dev` + clear build cache

**Fase 7 completada al 100% ✅ — 2026-04-09**

**Siguiente fase: Fase 8 — Catálogo completo + RBAC base**

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

- `.agents/rules/` — Reglas técnicas expandidas
- `.agents/workflows/` — Workflows de implementación, feature, seguridad
- `docs/product/current-scope.md` — Estado real de implementación hoy
- `docs/product/admin-ui-modules.md` — Módulos de ambas consolas con estado
- `docs/architecture/modules.md` — Responsabilidades de cada módulo backend
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend
- `docs/architecture/multi-tenant-security.md` — Contratos de RLS
- `docs/integrations/courier-envia.md` — Diseño de Shipping/Courier

## Stack — Versiones Reales en Repo

> Verificado en `apps/web/package.json` y `services/*/requirements.txt`.

| Capa | Versión real | Objetivo futuro |
|---|---|---|
| Frontend | Next.js **14.1.0** + React ^18 + TypeScript ^5 | Next.js 15.x |
| UI | TailwindCSS ^3.3.0 + shadcn/ui (5 componentes en `apps/web/components/ui/`) | Componentes en `packages/ui` |
| Backend | Python **3.9.25** (VM, EOL) + FastAPI 0.128.8 | Python 3.11+ |
| DB / Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) | — |
| IA | Google Gemini API (`google-genai==1.47.0`, modelo `gemini-2.5-flash`) | — |
| Mensajería | WhatsApp Cloud API (Meta oficial v21.0) | — |
| Shipping | Envia (📋 diseñado — no implementado) | — |
| Hosting | Render (Web Services + Background Workers) — Free plan | Starter antes de producción |

> `packages/ui` está vacío. Los componentes UI viven en `apps/web/components/ui/`.
> No asumir versiones de las docs — verificar siempre en `package.json` y `requirements.txt`.

## Crítico — Seguridad Git

- `.env` **NUNCA** va al repositorio. Config en Render Environment Variables.
- `node_modules/`, `.venv/`, `.next/` están en `.gitignore`.
