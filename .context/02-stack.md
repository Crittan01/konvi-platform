# Stack Técnico Real

> Verificar siempre en `apps/web/package.json` y `services/*/requirements.txt`. No asumir versiones.

## Frontend — `apps/web`

| Elemento | Versión real |
|---------|-------------|
| Next.js | **14.2.35** (App Router, Server Actions, Server Components) |
| React | ^18 |
| TypeScript | ^5 |
| TailwindCSS | ^3.3.0 |
| `@supabase/ssr` | ^0.10.0 |
| shadcn/ui | 5 componentes en `apps/web/components/ui/` |

⚠️ `packages/ui` está vacío. Los componentes UI viven en `apps/web/components/ui/`.

## Backend — servicios Python

| Elemento | Versión real |
|---------|-------------|
| Python (VM) | **3.11.13** (dnf, sin venv) — `Optional[X]` es el estilo del código |
| FastAPI | 0.128.8 |
| Pydantic | 2.12.5 |
| google-genai | 1.47.0 — SDK oficial Gemini (no usar `google-generativeai`) |
| supabase-py | 2.28.3 |
| GEMINI_MODEL | `gemini-2.5-flash` |

## Infraestructura

- **DB/Auth**: Supabase PostgreSQL + RLS + Auth + Realtime
- **Hosting**: Render (Free plan dev → Starter antes de producción)
- **Monorepo**: pnpm workspaces
- **SQL**: `supabase db query --linked -f archivo.sql` (psql TCP bloqueado por Supavisor)
