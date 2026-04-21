# Esquema de Datos (resumen operativo)

Última actualización: 2026-04-21

## Fuente canónica

`supabase/migrations/` es la única fuente de verdad del esquema SQL.

## Tablas núcleo (resumen)

- Tenancy y auth: `tenants`, `tenant_users`
- Conversacional: `conversations`, `messages`
- Catálogo: `products`, `product_variations`, `stock_movements`
- Ventas: `orders`, `order_items`, `contacts`, `claims`, `shipments`, `order_tracking`
- Integraciones: `tenant_integrations`, `notification_settings`, `integration_oauth_states`
- Observabilidad/seguridad: `audit_log`, `idempotency_keys`, `api_security_events`
- Planes: `billing_plans`, `plan_capabilities`, `tenant_subscriptions`, `tenant_usage_*`

## Regla de uso documental

Para cambios de esquema:

1. crear migración en `supabase/migrations/`
2. aplicar con `supabase db query --linked -f ...`
3. reflejar estado en `.context/01-state.md`
