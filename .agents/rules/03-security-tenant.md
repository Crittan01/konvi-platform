# Regla: Seguridad Multi-Tenant

## Modelo de aislamiento

- Toda operación atada a `tenant_id`
- `app_current_tenant()` resuelve desde JWT (`app_metadata.tenant_id`) o `app.current_tenant_id` de sesión Postgres
- RLS en todas las tablas con `tenant_id = app_current_tenant()`
- Workers: `service_role` + `SET app.current_tenant_id = '<uuid>'` antes de cada query

## Capas de seguridad (orden)

1. **Frontend** — no es seguridad, solo UX
2. **API Gateway** (`services/api`) — JWT validado, RBAC por endpoint
3. **RLS** — última barrera, siempre activa

## RBAC

- Roles: `owner`, `manager`, `agent` en `tenant_users`
- Plataforma (Fase 12): roles separados en `platform_users` — no mezclar con roles de tenant

## Reglas críticas

- `.env` NUNCA al repositorio
- `getUser()` en Server Components (no `getSession()`)
- Funciones `() => {}` no serializables como props RSC → props opcionales con default interno
