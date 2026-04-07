# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

## Estado Actual del Sistema — 2026-04-07T21:30 CDT

| Módulo | Estado | Notas |
|---|---|---|
| Supabase Cloud | ✅ Activo | proyecto `xmelwnhhphksbpdjmbbp` |
| Migraciones SQL (6) | ✅ Todas aplicadas | +`messages.processed` con índice parcial |
| Tenant activo | ✅ Configurado | `Matriz Commerce Dev`, `meta_waba_id=2159052118202272` |
| Frontend Backoffice | ✅ Funcional | Auth, Dashboard, Catálogo CRUD, **Inbox AI** |
| WhatsApp Connector | ✅ Fix aplicado | tenant resolver por `meta_waba_id` real |
| AI Orchestrator | ✅ Código completo | `worker`, `orchestrator`, `guardrails`, `sender` |
| Inbox AI Dashboard | ✅ Funcional | Realtime, Human Takeover, bubble UI |
| Deploy Render | ❌ Pendiente | Fase 7 |
| API Gateway real | 🟡 Pendiente | Fase 6 — mocks en `services/api` |
| Integración MeLi | ❌ Pendiente | Fase 8 |

**Credenciales activas (`.env` — nunca al repo):**
- `META_ACCESS_TOKEN`: renovado 2026-04-07 (~24h, renovar periódicamente — ver [IH-003])
- `GEMINI_API_KEY`: **pendiente configurar** para activar el Orchestrator
- `meta_waba_id`: `2159052118202272` ✅

**Herramientas instaladas en VM (sin venv — máquina dedicada):**
- `supabase` CLI v2.84.2 → migraciones via `supabase db query --linked -f archivo.sql`
- `psql` 15.17 → disponible pero Supavisor bloquea TCP desde esta IP (usar CLI)
- `pip3` sistema: `supabase`, `google-generativeai`, `httpx`, `pydantic`, `python-dotenv`

## Próximo a Implementar

**Fase 6 — API Gateway real** (`services/api`): reemplazar mocks con lógica real + RLS.
**Fase 7 — Deploy en Render**: `render.yaml` y vars de entorno en Render Dashboard.

> Para activar el AI Orchestrator hoy: agregar `GEMINI_API_KEY` al `.env` y ejecutar `python3 services/ai-orchestrator/main.py`

Ver detalles completos en: `docs/architecture/modules.md` y `docs/roadmap/implementation-phases.md`.

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
