# @commerce/config

Última actualización: 2026-04-21

## Estado

Activo mínimo.

## Contenido actual

- `eslint/base.cjs` — baseline de ESLint
- `tailwind/preset.cjs` — preset base de Tailwind
- `tsconfig/base.json` — baseline de TypeScript

## Alcance

No está cableado globalmente aún; se mantiene como capa lista para reuso gradual.
Esto evita sobreingeniería mientras solo existe una app frontend.

## Referencia

Uso objetivo cuando se decida consolidar:
- `apps/web/.eslintrc.json`
- `apps/web/tailwind.config.ts`
- `apps/web/tsconfig.json`
