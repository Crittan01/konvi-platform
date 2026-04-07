# Workspace AI Guidelines

Este repositorio es la matriz de un producto **SaaS Conversacional Multi-Tenant** para operación e-commerce vía WhatsApp.

## Contexto del Producto

- **Propósito**: Plataforma B2B2C que automatiza ventas y atención al cliente por WhatsApp usando IA.
- **Tenants**: Cada cliente (empresa) es un tenant con aislamiento total de datos vía RLS en PostgreSQL.
- **Canal oficial**: WhatsApp Cloud API (Meta) — sin librerías no oficiales.
- **IA**: Google Gemini API con output estructurado Pydantic — el LLM nunca es fuente de verdad de datos.

## Estado Actual del Sistema (Abril 2026)

| Módulo | Estado |
|---|---|
| Supabase Cloud | ✅ Provisionado — proyecto `xmelwnhhphksbpdjmbbp` |
| Migraciones SQL (5) | ✅ Aplicadas — tenants, catálogo, conversaciones, RLS, JWT claims |
| Frontend Backoffice | ✅ Funcional — Auth, Dashboard, Catálogo CRUD |
| WhatsApp Webhook | 🟡 Parcial — **tenant resolver hardcodeado, pendiente fix** |
| AI Orchestrator | ❌ En implementación activa |
| Inbox AI Dashboard | ❌ En implementación activa |
| Deploy Render | ❌ Pendiente |

## Próximo Módulo a Implementar

**AI Orchestrator** — ciclo completo: mensaje entrante → contexto del tenant → Gemini → guardrail → respuesta WhatsApp.

Ver detalles del plan en: `docs/architecture/modules.md` y `docs/roadmap/implementation-phases.md`.

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
