# Entornos de Deployment

Última actualización: 2026-04-21

## Entornos activos

| Entorno | URL | Rama | Auto-deploy |
|---|---|---|---|
| Producción/Lab compartido | `https://commerce-ops-web.onrender.com` | `develop` | Sí |
| Local | `http://localhost:3000` + servicios Python locales | N/A | Manual |

> Si la rama de auto-deploy cambia en Render, `docs/HANDOFF.md` debe actualizarse en la misma sesión.

## Servicios de producción/lab

- `commerce-ops-web`
- `commerce-ops-connector`
- `commerce-ops-api`
- `commerce-ops-orchestrator`

## Staging

No existe staging dedicado aún.

## Política de upgrade pago

La transición a planes pagos debe ocurrir cerca de salida productiva o ante bloqueante operativo real.
Ver `docs/deployment/render-upgrade-path.md`.
