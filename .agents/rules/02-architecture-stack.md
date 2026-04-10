# Regla: Arquitectura y Stack

## Stack real vigente

- **Frontend**: Next.js 14.2.35 (App Router), React ^18, TypeScript ^5, TailwindCSS ^3.3.0
- **Backend**: Python 3.9.25 (VM, EOL), FastAPI 0.128.8, google-genai==1.47.0
- **DB/Auth**: Supabase PostgreSQL + RLS + Auth + Realtime
- **Hosting**: Render (Web Services + Background Workers)

> Verificar versiones en `apps/web/package.json` y `services/*/requirements.txt`. No asumir.
> Stack completo → `.context/02-stack.md`

## Restricciones

- `packages/ui` está vacío — componentes UI en `apps/web/components/ui/`
- `packages/db/migrations/` son mirrors parciales — fuente real: `supabase/migrations/`
- Python 3.9: usar `Optional[X]` no `X | None`
- Next.js SSR: usar `getUser()` no `getSession()`
