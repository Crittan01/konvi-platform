# Monorepo Packages (estado vigente)

Última actualización: 2026-04-21

## Decisión actual

Mantener una arquitectura de paquetes compartidos **mínima y útil**, sin forzar consumo por `workspace:*` mientras el build productivo de `apps/web` siga en `npm install` dentro de Render.

## Estado por paquete

| Paquete | Estado | Decisión |
|---|---|---|
| `@commerce/shared-types` | Activo mínimo | Contratos TS canónicos de dominio (roles, estados, planes/capabilities). |
| `@commerce/config` | Activo mínimo | Presets base de ESLint/Tailwind/TS para reuso gradual. |
| `@commerce/auth` | Activo parcial | Wrappers SSR existentes; no consolidado aún en `apps/web`. |
| `@commerce/observability` | Preparado | Sin SDK central; observabilidad runtime sigue en logs + DB. |
| `@commerce/ui` | Deferred | Mantener componentes en `apps/web/components/ui/` mientras haya una sola app frontend. |
| `@commerce/test-utils` | Deferred | Activar cuando exista suite compartida cross-paquete. |
| `@commerce/db` | Snapshot legacy | No canónico; esquema real en `supabase/migrations/`. |

## Regla de consumo (importante)

No introducir dependencia `workspace:*` en `apps/web` hasta cambiar la estrategia de build/deploy que hoy usa `npm install` en `rootDir`.

## Source of truth

- Estado operativo: `.context/01-state.md`
- Próximos pasos: `.context/04-next-steps.md`
- Inventario de paquetes: `packages/README.md`
