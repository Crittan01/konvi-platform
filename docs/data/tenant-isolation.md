# Tenant Isolation

## Objetivo
Documentar cómo se garantiza el aislamiento entre clientes.

## Mecanismos
- tenant_id
- RLS
- claims/JWT
- RBAC por tenant
- storage segregado
- integraciones segregadas
- auditoría

## Regla
Todo acceso cruzado entre tenants debe estar explícitamente prohibido salvo mecanismos de soporte controlados y auditados.