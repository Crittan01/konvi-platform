# Multi-Tenant Security

## Objetivo
Garantizar separación real entre clientes.

## Mecanismos obligatorios
- tenant_id en entidades relevantes
- RLS en tablas sensibles
- RBAC por tenant
- claims en JWT
- storage segregado
- integraciones segregadas por tenant
- auditoría de acciones administrativas

## Regla importante
Subdominio no equivale a seguridad.
La seguridad vive en Auth + RBAC + RLS + storage policies + auditoría.