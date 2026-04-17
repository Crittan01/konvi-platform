# CLAUDE.md — Commerce Ops Platform

Contexto estable del proyecto para desarrollo.
No sustituye validaciones en código, documentación oficial ni checks del repositorio.
La fuente de verdad del árbol funcional es `.context/00-product.md`.

---

## Qué es este proyecto

SaaS conversacional multi-tenant para e-commerce B2B2C vía WhatsApp.
Cada empresa (tenant) opera con aislamiento total de datos.
WhatsApp Cloud API (Meta oficial) es el canal de ventas.
La IA (Gemini) es asistencia, nunca fuente de verdad de datos operacionales.

**Estado**: Fases 1-11.5 completadas (incl. Reclamos, Compras, Finanzas, Marketplace). Live en Render. Fase 12 (Platform Console) bloqueada por OQ-P01 — fuera de alcance.

---

## Stack

| Capa        | Versión                                     | Notas                          |
| ----------- | ------------------------------------------- | ------------------------------ |
| Frontend    | Next.js 14.2.35 + React 18 + TypeScript 5   | App Router + Route Groups      |
| UI          | TailwindCSS 3.3 + shadcn/ui (11 componentes) | Dark Warm Theme — HSL tokens  |
| Backend     | Python 3.11.13 + FastAPI 0.128.8            | Sin venv — paquetes en sistema |
| DB/Auth     | Supabase PostgreSQL + RLS + Auth + Realtime | 25 migraciones aplicadas       |
| IA          | `google-genai==1.47.0` — `gemini-2.5-flash` | SDK oficial                    |
| WhatsApp    | WhatsApp Cloud API v21.0                    | Solo oficial Meta              |
| Shipping    | Envia API                                   | Fase Inicial live              |
| Marketplace | Mercado Libre OAuth 2.0                     | Listings live                  |
| Hosting     | Render — 4 servicios (Free)                 | `render.yaml` IaC              |

Verificar siempre versiones reales en `package.json` y `requirements.txt`.

---

## Estructura de Directorios Clave

```
apps/web/app/dashboard/
  (sales)/        → /orders, /contacts, /shipping, /claims
  (products)/     → /catalog, /inventory, /media
  (channels)/     → /marketplace
  (ai)/           → /knowledge-base, /ai-agents
  (analytics)/    → /metrics, /audit
  (settings-group)/ → /settings, /integrations
  inbox/          → /inbox
  finance/        → /finance
  purchases/      → /purchases

services/
  api/            → FastAPI Core (9 routers)
  connector-whatsapp/ → Webhook Meta
  ai-orchestrator/    → Polling Gemini

supabase/migrations/  → Fuente canónica de esquema DB (25 migraciones)
```

> Route Groups `(nombre)` no modifican URLs. `(sales)/orders/page.tsx` → `/dashboard/orders`.

---

## Principios Críticos

1. Multi-tenant desde el día 1. Toda tabla operativa tiene `tenant_id`.
2. RLS es la última barrera. El frontend no es seguridad.
3. En Server Components usar `getUser()`, nunca `getSession()`.
4. Gemini no decide verdad transaccional.
5. Solo WhatsApp Cloud API oficial. Nada no oficial.
6. Todo integrador externo desacoplado del núcleo.
7. Leer `.context/00-product.md` **antes** de crear o mover un módulo.
8. Platform Console fuera de alcance — no tocar.

---

## Comandos Frecuentes

```bash
# Frontend dev
pnpm --filter web dev

# Migración SQL
supabase db query --linked -f supabase/migrations/archivo.sql

# AI Orchestrator local
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py
```

---

## Lecciones Críticas (No Repetir)

- `google-generativeai` deprecado → usar `google-genai==1.47.0`
- `getSession()` inseguro en Server Components → siempre `getUser()`
- `NODE_ENV=production` + `npm install` omite devDeps → `--include=dev`
- `psql` TCP bloqueado por Supavisor → `supabase db query --linked`
- ESLint v10 incompatible con Next.js 14 → `eslint@8`
- Funciones arrow `() => {}` como props RSC no son serializables → props opcionales con default interno
- `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
- Si CSS se ve plano en Render → "Clear build cache & deploy"

## Política de brevedad

- Responder con la menor cantidad de texto posible sin perder precisión, trazabilidad ni seguridad.
- Evitar relleno, repeticiones, muletillas y explicaciones obvias.
- Expandir solo cuando haya riesgo, ambigüedad, decisiones irreversibles o impacto arquitectónico.
- No sacrificar contexto crítico por brevedad.
