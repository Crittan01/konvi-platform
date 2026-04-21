# Paquetes Compartidos del Monorepo

Última actualización: 2026-04-21

## Estado por paquete

| Paquete | Estado | Propósito |
|---|---|---|
| `@commerce/shared-types` | Activo mínimo | Contratos TS canónicos (roles, estados, planes/capabilities). |
| `@commerce/auth` | Activo parcial | Wrappers SSR Supabase reutilizables (aún no consolidados en `apps/web`). |
| `@commerce/config` | Activo mínimo | Presets base de ESLint, Tailwind y TS para reuso gradual. |
| `@commerce/observability` | Preparado | Reserva técnica para estandarizar contratos de eventos/logging. |
| `@commerce/ui` | Deferred | No extraer componentes mientras exista una sola app frontend. |
| `@commerce/test-utils` | Deferred | Activar al tener suite compartida cross-paquete. |
| `@commerce/db` | Snapshot legacy | No canónico; esquema real vive en `supabase/migrations/`. |

## Regla de consumo

No introducir `workspace:*` en `apps/web` mientras el build productivo siga usando `npm install` en `rootDir` de Render.

## Referencia técnica

Ver decisión extendida: `docs/tech/monorepo-packages.md`.
