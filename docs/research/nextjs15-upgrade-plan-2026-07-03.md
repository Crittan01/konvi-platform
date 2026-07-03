# Plan de upgrade Next.js 14.2.35 → 15.5.x (+ React 19)

**Motivo (Fase 6 audit):** Next.js 14.x es **EOL** (sin parches desde oct-2025). La
release de seguridad may-2026 (bypass de auth basado en middleware, SSRF, cache poisoning)
NO parchea 14.x. Único fix = upgrade mayor a 15.x/16.x.

**Por qué no lo apliqué yo:** `npm install` está roto en el entorno de trabajo del agente
(bug de arborist "Cannot read properties of null" que afecta CUALQUIER config, incl. Next 14).
No pude instalar Next 15 ni correr `next build` para validar. Hacer los ~174 edits del
async-migration a ciegas sería temerario. Este plan es para ejecutar en un entorno con npm
funcional (tu máquina / CI).

## 0. Preparación
- Rama dedicada: `git checkout -b upgrade/next15`.
- Confirmar npm funcional: `npm install` sin errores en el estado actual (Next 14).

## 1. package.json (apps/web) — bumps
```
"next": "15.5.20",
"react": "^19.0.0",
"react-dom": "^19.0.0",
"eslint-config-next": "15.5.20",
"@types/react": "^19",
"@types/react-dom": "^19",
```
Verificar compat React 19 de: `@sentry/nextjs ^8.55` (8.x soporta Next 15/React 19),
`recharts ^3.8` (peer React 19 OK), `@radix-ui/*` (1.2.x soportan React 19),
`lucide-react`. Si algún peer falla → `npm install` lo reporta; subir a la versión que
declare React 19 en peerDependencies. `@supabase/ssr ^0.10` YA soporta cookies async.

## 2. Async Request APIs — codemod oficial primero
```
npx @next/codemod@latest next-async-request-api .
```
Convierte automáticamente: `cookies()`/`headers()`/`draftMode()` a `await`, y
`params`/`searchParams` de páginas/layouts a `Promise` awaited. Superficie medida:
- `cookies()`: 3 archivos (`utils/supabase/server.ts`, `app/dashboard/layout.tsx`, `app/auth/confirm/route.ts`)
- `headers()`: 1 archivo
- `params`/`searchParams` en `page.tsx`/`layout.tsx`: 18 archivos

## 3. `createClient()` server — CASCADA MANUAL (el codemod NO la cubre)
`utils/supabase/server.ts::createClient()` llama `cookies()` sync. En Next 15 debe ser
**async** (el cookie store es async). Reescribir a `async function createClient()` con
`const cookieStore = await cookies()` y migrar el adapter a la API `getAll`/`setAll` de
`@supabase/ssr` 0.10 (recomendada). Luego:
- **174 call sites** de `= createClient()` en **92 archivos** → `= await createClient()`.
  Sweep (verificar cada uno queda en scope async — server components/actions ya lo son):
  ```
  grep -rl "= createClient()" apps/web/app | xargs sed -i 's/= createClient()/= await createClient()/g'
  ```
  Luego `next build` reporta cualquier `await` en función no-async → convertir esa función a async.
- NO tocar `utils/supabase/client.ts` (browser client, sin cookies async) ni `admin.ts`.

## 4. Caching (cambio de comportamiento runtime — NO lo detecta `next build`)
Next 15 cambió defaults: `fetch()` ya NO se cachea por defecto, y los GET Route Handlers
ya NO se cachean por defecto. Auditar `apps/web` por dependencias implícitas de caché.
Este código usa mayormente RSC + `revalidatePath` explícito, bajo riesgo, pero validar en QA:
inbox realtime, dashboards, listados. Si algo dependía del cache implícito → `export const dynamic`/`revalidate` explícito.

## 5. Validación (obligatoria antes de merge)
```
cd apps/web
npm install
npx tsc --noEmit          # contrato de tipos (React 19 + async APIs)
npm run build             # next build — DEBE pasar
npm run lint              # eslint-config-next 15
npm test                  # vitest
```
Desde raíz: `bash scripts/validate.sh --ci` (incluye el build).

## 6. QA runtime en preview de Render (deploy-verify)
Desplegar la rama a un servicio preview de Render y verificar: login + MFA/AAL2 gate,
inbox, creación de pedido + link Wompi, catálogo, dashboards. El gate MFA/AAL2 es la
superficie que el advisory de middleware-bypass afecta — confirmar que sigue enforcing.

## Notas de seguridad (mientras se agenda el upgrade)
La autorización de DATOS ya es defensa-en-profundidad e independiente del middleware Next:
RSC llaman `getUser()`/`getCachedTenantMeta()` server-side, y FastAPI valida JWT + RLS
por su cuenta. El residual del bypass es el gate MFA/AAL2 (solo-middleware, `middleware.ts:87`).
Si el upgrade se demora, evaluar replicar el check AAL2 en `app/dashboard/layout.tsx`
(server-side, fail-open ante error de red como el middleware) — cambio acotado pero que
requiere deploy-verify por riesgo de lockout.
