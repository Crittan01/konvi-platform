# @commerce/observability — DEFERRED

**Estado**: Intencionalmente vacío.

**Propósito potencial**: Capa de observabilidad compartida entre servicios:
- Structured logging (JSON) estandarizado para todos los servicios Python
- Wrappers de trazas distribuidas (OpenTelemetry)
- Alertas programáticas (Telegram, PagerDuty)
- Métricas de negocio (custom events)

**Estado actual de observabilidad**:
- Logs: stdout en cada servicio → Render Dashboard (retención 7 días en Free)
- Auditoría de negocio: tabla `audit_log` en Supabase (ver migración `20260409260000`)
- Alertas: Telegram via `notification_settings` (configurado por tenant)

**Cuándo poblarlo**: Cuando el volumen de tenants justifique logging centralizado (Datadog, Sentry,
Grafana Cloud) o cuando los logs de Render sean insuficientes para debugging en producción.

**No abstraer aquí** hasta que el problema sea concreto. Logging en stdout es suficiente para Beta.
