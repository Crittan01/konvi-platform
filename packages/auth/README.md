# @commerce/auth — Wrappers Supabase SSR

Última actualización: 2026-04-16

## Estado

**Parcialmente implementado. No consumido actualmente por `apps/web`.**

`apps/web` usa sus propios helpers en `apps/web/utils/supabase/`:
- `server.ts` — cliente SSR para Server Components/Actions
- `client.ts` — cliente browser para Client Components
- `admin.ts` — cliente Service Role para operaciones privilegiadas
- `middleware.ts` — gestión de sesión en middleware Next.js

## Contenido actual

| Archivo | Descripción |
|---------|-------------|
| `lib/client-browser.ts` | Wrapper `createBrowserClient` de `@supabase/ssr` |
| `lib/server-client.ts` | Wrapper `createServerClient` de `@supabase/ssr` |

## Cuándo consolidar

Este paquete tiene sentido cuando:
1. Haya una segunda app (Platform Console — Fase 12) que necesite los mismos wrappers
2. O se decida eliminar la duplicación entre `packages/auth/lib/` y `apps/web/utils/supabase/`

**Si se consolida**: `apps/web/package.json` debe agregar `"@commerce/auth": "workspace:*"` y
los imports en toda la app deben migrar de `utils/supabase/` a `@commerce/auth`.

## Seguridad

- El cliente admin (Service Role) **nunca** debe exportarse desde este paquete con acceso público
- `SUPABASE_SERVICE_ROLE_KEY` nunca con prefijo `NEXT_PUBLIC_`
- Solo usar `adminClient` en Server Actions con guard de rol explícito antes de llamarlo
