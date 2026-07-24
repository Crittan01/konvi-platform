# Next.js 15 → 16 — migración mayor (pre-launch)

**PR #152** · rama `chore/next-16-upgrade` · base `develop`. Ejecutado 2026-07-24.
Deploy **gated a OK founder** (pre-launch; sin cambio de runtime en prod).

## Por qué ahora (revirtiendo el "diferir")

El assessment previo recomendaba diferir por el "riesgo del cambio de caching en
producción". El founder corrigió dos premisas:

1. **KAIU está pre-lanzamiento** (no productivo). El riesgo de caching que citaba es
   un riesgo de *tráfico de producción* — que no existe hoy. Este es el window para el
   que existe el modo `prelaunch`.
2. **3 meses al EOL** (Next 15 EOL 2026-10-21) es poco para un major de framework.
   Hacerlo con runway y sin usuarios es más prudente que rushearlo al final, o con
   clientes adentro.

Conclusión: se hace ahora.

## Alcance ejecutado

| Cambio | Detalle |
|---|---|
| `next` 15.5.21 → **16.2.11** | LTS actual de la línea 16 |
| `eslint-config-next` → **16.2.11** | apunta al plugin de Next 16 |
| ESLint 8 → **9** + **flat config** | `next lint` REMOVIDO en 16 → `.eslintrc.json` → `eslint.config.mjs`; `lint` = CLI de ESLint |
| `@sentry/nextjs` 8 → **10.68.0** | companion REQUERIDO (peer de v8 topa en Next 15; v10.20+ soporta `^16`) |
| scripts `dev`/`build` → `--webpack` | mantiene sourcemaps de Sentry v10 + paridad dev/build |

### Async Request APIs — cero cambios de código
Todas las páginas **ya** tipaban `params`/`searchParams` como `Promise<...>` y los
awaitaban (el patrón async de Next 15 ya estaba adoptado en todo el código). El codemod
oficial `next-async-request-api` fue **net-negativo** (insertó comentarios
`@next-codemod-error` espurios sobre `await import('next/headers')` — que ya estaba
correcto — y churn cosmético de JSX) → **revertido**. La migración se validó con tsc +
`next build` (que genera los route-types y valida `PageProps` async).

### ESLint flat config — decisiones
- `eslint-config-next` 16 exporta un **flat config array NATIVO** (`Linter.Config[]`)
  que agrupa next-plugin + react + react-hooks + typescript-eslint + import + jsx-a11y.
  Se **importa y spreadea directo** — NO via `FlatCompat`, que choca con
  `TypeError: Converting circular structure to JSON` al serializar el plugin react.
- **NO** se añade `js.configs.recommended`: reintroduce `no-undef`/`no-unused-vars`
  base, que dan ~190 falsos positivos (`'React' is not defined`) sobre JSX con runtime
  automático. El flat de next ya es autocontenido (patrón de `create-next-app` 16).
- Overrides scopeados a `**/*.{ts,tsx}` (en flat config los plugins se mergean
  por-archivo; sin `files` fallaría sobre `.js`/`.mjs`).
- Reglas **nuevas** del React Compiler (`react-hooks/purity` — `Date.now()` en render
  de Server Component; `react-hooks/set-state-in-effect`) → **`warn`**: un bump de deps
  no debe forzar refactors de código que funciona. Follow-up de calidad.

### Sentry v8 → v10
- Peer de `@sentry/nextjs` v8 = `^13 || ^14 || ^15`; **v10.20+ agrega `^16`**. No es solo
  Turbopack: es compat del SDK entero (withSentryConfig + auto-instrumentación).
- `withSentryConfig` pasó de **3 args a 2** (v9): `hideSourceMaps` removido (v9+ borra
  sourcemaps tras subirlos), `automaticVercelMonitors` → `webpack.automaticVercelMonitors`.
- `sentry.client.config.ts` sigue soportado (el build lee ese nombre y
  `instrumentation-client.ts`); `captureRequestError` y `browserTracingIntegration` intactos.

## Caching de Next 16 — riesgo verificado NULO

Auditoría multi-agente (5 lectores sobre fetch / route-config / cache-apis /
data-Supabase / dynamic-render) + build real:

- Cache Components / `"use cache"` / `dynamicIO` son **opt-in**; `next.config.js` NO los
  activa. Cero opt-ins de cache en todo el código (0 `force-cache`, 0 `next:{revalidate}`,
  0 `unstable_cache`, 0 `"use cache"`, 0 `fetchCache`).
- El salto que flipeó fetch→`no-store` fue **14→15** (ya lo teníamos en 15.5.21).
- La data viene del **cliente Supabase** (`createServerClient` lee `cookies()` por-request)
  → transparente al cache de Next; las mutaciones son POST/PATCH que Next nunca cachea.
- Solo usamos `revalidatePath` (API **estable**, firma sin cambios en 16, siempre
  single-arg en Server Actions). NO usamos `revalidateTag` (el que ahora exige 2º arg).

**Prueba empírica — tabla de rutas del build:** todas las `/dashboard/*` y `/api/*` salen
`ƒ` (Dynamic, server-rendered); la única static (`○`) es `/dashboard/settings/legal/view/[doc]`
(lee `.md` por `node:fs`, sin fetch). **Idéntico a Next 15** — ninguna ruta autenticada se
volvió estática.

## Verificación (Node 22)

- `next build --webpack`: **EXIT 0**, "Compiled successfully", 60 páginas estáticas
  generadas. Único warning: deprecación `middleware`→`proxy` (diferida, ver abajo).
- ESLint flat: **0 errores**, 38 warnings (rc 0). Compatible con la clasificación de
  `validate.sh` (probado: reporta "OK con warnings no bloqueantes").
- Vitest: **269/269** (28 archivos).
- tsc: 0 errores (type-check del build).

## Diferido deliberadamente (follow-ups aislados)

1. **`middleware.ts` → `proxy.ts`** — deprecación (warning en build, NO error; `middleware`
   funciona en 16). `proxy` corre en **nodejs** (NO edge, no configurable) y toca código
   **auth/MFA crítico** → merece su propia validación (login/MFA/recovery), no bundlearlo
   en un bump de deps.
2. ~~**Turbopack build**~~ — **HECHO** (follow-up PR, ver §Turbopack abajo).
3. **Refactor** de los `react-hooks/purity` + `set-state-in-effect` (hoy `warn`).

## Turbopack (follow-up — adopción del bundler default de Next 16)

`dev`+`build` pasaron de `--webpack` a **Turbopack** (default de 16), desbloqueado por Sentry v10.

- **Build verificado** (Node 22): `▲ Next.js 16.2.11 (Turbopack)` — EXIT 0, "Compiled
  successfully". **La tabla de rutas es BYTE-IDÉNTICA a la de webpack** (78 rutas, diff vacío):
  ninguna ruta cambió de `ƒ`/`○`, ninguna autenticada se volvió estática. Mismo comportamiento
  de routing/caching.
- **Sentry v10 + Turbopack** (verificado en los types del SDK): los **sourcemaps SÍ se suben**
  vía el hook `runAfterProductionCompile` (`useRunAfterProductionCompileHook` default `true`
  para Turbopack). Bajo Turbopack, Sentry deja su instrumentación build-time propia y usa la
  **telemetría nativa de Next.js**; el único efecto es que `excludeServerRoutes` haría no-op
  — que **no usamos**. La captura de errores server-side sigue intacta vía `instrumentation.ts`
  (`register()` + `captureRequestError`), el enfoque moderno bundler-agnóstico que ya teníamos.
- Sin config `turbopack.*` en `next.config.js` (no usamos loaders/aliases custom) → nada que migrar.

## Plan de validación pre-deploy (cuando el founder dé OK)

1. `bash scripts/validate.sh --ci` verde en la rama (build + TS + ESLint + suite).
2. `next start` local + smoke con 2 usuarios de tenants distintos: dashboard/orders/finance/
   contacts/metrics — cada sesión ve SOLO su tenant (cero cache cross-tenant). Headers de
   páginas autenticadas = no-store/private.
3. `revalidatePath` e2e: una mutación (crear categoría / cambiar estado de orden) refleja
   el cambio sin recarga dura.
4. Visor legal `force-static` renderiza el Markdown correcto.
5. Deploy `git push origin origin/develop:production` + health de los 4 servicios.

Node 22 (prerequisito de compat) ya está en prod → sin cambio de runtime.
