# Onboarding de Tenants

Última actualización: 2026-04-21

## Estado actual

Onboarding asistido/manual (Platform Console aún no implementada).

## Flujo asistido vigente

1. Crear tenant en `tenants`.
2. Crear usuario en Supabase Auth.
3. Vincular usuario en `tenant_users` con rol `owner`.
4. Configurar integraciones por tenant desde `/dashboard/integrations`.
5. Validar login, navegación y módulos críticos (Inbox, catálogo, pedidos).

## Flujo objetivo futuro

Self-serve desde Platform Console (fase 12, bloqueada por OQ-P01).

## Referencias

- `docs/architecture/multi-tenant-security.md`
- `docs/data/schema.md`
- `docs/HANDOFF.md`
