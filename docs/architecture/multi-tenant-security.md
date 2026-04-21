# Seguridad Multi-Tenant (modelo vigente)

Última actualización: 2026-04-21

## Capas de seguridad

1. API Gateway (`services/api`)  
- valida JWT
- extrae `tenant_id` y `role`
- aplica RBAC + hardening

2. Base de datos (Supabase / RLS)  
- políticas por `tenant_id`
- funciones SQL de apoyo (`app_current_tenant()`)

3. Frontend  
- solo UX y gating visual (no seguridad)

## Regla crítica

`service_role` puede bypassar RLS.  
Por tanto, todo path privilegiado debe filtrar explícitamente por `tenant_id`.

## Contratos runtime de identidad

- Roles activos: `owner`, `manager`, `operator`
- Estados canónicos conversación: `bot_active`, `human_takeover`, `closed`
- Mensajes inbound/outbound: `processing_status` (`pending|processed|skipped|failed`)

## Prácticas obligatorias

- Nunca exponer `SUPABASE_SERVICE_ROLE_KEY` al cliente.
- No confiar seguridad solo en sidebar o locks UX.
- En workers, mantener scoping explícito de tenant.
