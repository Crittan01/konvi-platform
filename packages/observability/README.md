# @commerce/observability

Última actualización: 2026-04-21

## Estado

Preparado con contrato mínimo.

## Contenido actual

- `src/index.ts` con tipos canónicos para:
  - eventos de seguridad API
  - snapshots de salud de colas async

## Límites actuales

No existe SDK centralizado de logging/tracing en runtime.

La operación sigue en:
- logs stdout por servicio (Render)
- tablas de auditoría/seguridad en Supabase (`audit_log`, `api_security_events`)

## Cuándo escalar este paquete

Cuando se implemente instrumentación transversal (OpenTelemetry/Sentry/Datadog) o agregación formal de métricas por tenant/cola.
