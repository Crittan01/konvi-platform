# @commerce/config — DEFERRED

**Estado**: Intencionalmente vacío.

**Propósito potencial**: Centralizar configuraciones compartidas del monorepo:
- `eslint-config-commerce` — reglas ESLint comunes
- `tsconfig-commerce` — base TypeScript
- `tailwind-preset-commerce` — tokens de diseño (Dark Warm Theme)

**Cuándo poblarlo**: Cuando haya una segunda app (`apps/platform/`) que necesite las mismas reglas.
Con una sola app, la duplicación es mínima y no justifica la abstracción.

**Referencia**: `apps/web/.eslintrc.json`, `apps/web/tailwind.config.ts`, `apps/web/tsconfig.json`
