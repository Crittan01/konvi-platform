# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

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
| Deploy Render (Fase 7) | 🟡 PASO 5 ✅ | Pendiente: PASO 6 (Meta Webhook) + PASO 7 (E2E) |
| `services/orchestrator/` | ✅ ELIMINADO | Prototipo obsoleto — canónico: `services/ai-orchestrator/` |
| Integración MeLi | ❌ Pendiente | Fase 8 |

**Credenciales activas (`.env` — nunca al repo) — estado 2026-04-09:**
- `META_ACCESS_TOKEN`: ✅ En Render Dashboard — **⚠️ token temporal ~24h, migrar a System User Token (IH-006)**
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

**Pendiente (requiere acción humana):**
1. **[IH-006]** → crear System User Token permanente en Meta Business Suite
2. **PASO 6** → actualizar Callback URL en Meta Developers → `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook` + Verify Token `***META_VERIFY_TOKEN_LEGACY_REDACTED***`
3. **PASO 7** → Test E2E — enviar WhatsApp desde celular → verificar respuesta automática de Gemini

**Siguiente fase: Fase 8 — Integración Mercado Libre**

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
- `docs/architecture/modules.md` — Responsabilidades de cada módulo
- `docs/architecture/multi-tenant-security.md` — Contratos de RLS

## Stack Obligatorio

| Capa | Tecnología |
|---|---|
| Frontend | Next.js 15 + React + TypeScript + TailwindCSS + shadcn/ui |
| Backend | Python 3.11+ + FastAPI |
| DB / Auth | Supabase (PostgreSQL + RLS + Auth + Realtime) |
| IA | Google Gemini API |
| Mensajería | WhatsApp Cloud API (Meta oficial) |
| Hosting | Render (Web Services + Background Workers) |

## Crítico — Seguridad Git

- `.env` **NUNCA** va al repositorio. Config en Render Environment Variables.
- `node_modules/`, `.venv/`, `.next/` están en `.gitignore`.
