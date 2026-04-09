# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

## Estado Actual del Sistema — 2026-04-08T20:30 CDT

| Módulo | Estado | Notas |
|---|---|---|
| Supabase Cloud | ✅ Activo | proyecto `***SUPABASE_PROJECT_REF_REDACTED***` |
| Migraciones SQL (6) | ✅ Todas aplicadas | +`messages.processed` con índice parcial |
| Tenant activo | ✅ Configurado | `Matriz Commerce Dev`, `meta_waba_id=2159052118202272` |
| Frontend Backoffice | ✅ Funcional | Auth, Dashboard, Catálogo CRUD, Inbox AI |
| WhatsApp Connector | ✅ Fix aplicado | tenant resolver por `meta_waba_id` real |
| AI Orchestrator | ✅ Código completo | `google-genai==1.47.0`, server.py wrapper para Render Free |
| Inbox AI Dashboard | ✅ Funcional | Realtime, Human Takeover, bubble UI |
| API Gateway (Fase 6) | ✅ Completa | JWT real, productos CRUD, conversaciones |
| render.yaml | ✅ Actualizado | 4 servicios: web + connector + api + orchestrator |
| Deploy Render (Fase 7) | 🟡 En progreso | IH-004 — ver `docs/deployment/FASE7_RENDER_DEPLOY.md` |
| `services/orchestrator/` | ✅ ELIMINADO | Prototipo obsoleto — canónico: `services/ai-orchestrator/` |
| Integración MeLi | ❌ Pendiente | Fase 8 |

**Credenciales activas (`.env` — nunca al repo):**
- `META_ACCESS_TOKEN`: renovado 2026-04-07 ∼16:41 CDT (∼24h, ver [IH-003]) — **⚠️ renovar si expirado**
- `GEMINI_API_KEY`: ✅ configurada en `.env`
- `SUPABASE_JWT_SECRET`: ⚠️ **PENDIENTE** — obtener de Supabase Dashboard → Project Settings → Data API
- `meta_waba_id`: `2159052118202272` ✅

**Herramientas instaladas en VM (sin venv — máquina dedicada):**
- `supabase` CLI v2.84.2 → `supabase db query --linked -f archivo.sql`
- `psql` 15.17 via DNF (TCP bloqueado por Supavisor — usar CLI)
- `pip3` sistema: `google-genai==1.47.0`, `supabase==2.10.0`*, `httpx==0.28.1`, `pydantic==2.12.5`, `PyJWT==2.10.1`, `fastapi==0.115.12`, `uvicorn[standard]==0.34.0`
- Python 3.9.25 (sistema Oracle Linux 9) — compatible con `Optional[]`, no `X | Y`
- ⚠️ *`supabase==2.10.0` en VM pero requirements.txt usa `2.28.3`. Para alinear: `pip3 install supabase==2.28.3`

## Próximo a Implementar

**Fase 7 — Deploy en Render** (próxima prioridad):
> Ver guía detallada: `docs/deployment/FASE7_RENDER_DEPLOY.md`

1. PRE-REQ: Obtener `SUPABASE_JWT_SECRET` de Supabase Dashboard → Project Settings → Data API
2. **Humano** → crear cuenta Render + Blueprint con repo `Crittan01/commerce-ops-platform` (IH-004)
3. **Humano** → configurar env vars secretas en Render Dashboard para cada servicio
4. **Agente** → smoke tests y verificación de health checks
5. **Humano** → actualizar Callback URL del webhook en Meta Developers
6. Test E2E — mensaje WhatsApp → Gemini → respuesta automática

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
