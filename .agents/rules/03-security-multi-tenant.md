---
trigger: always_on
---

# Seguridad y multi-tenant

Obligatorio:
- tenant_id en entidades relevantes
- RLS en tablas sensibles
- RBAC por tenant
- storage segregado
- auditoría
- separación entre tenant admin y superadmin
- service role restringido
- validación de webhooks
- signed URLs para media sensible cuando aplique

## Regla importante
El subdominio no es seguridad.
La seguridad vive en Auth + claims + RBAC + RLS + storage policies + auditoría.

## Restricciones
- nunca usar service role en frontend
- no mezclar integraciones entre tenants
- toda acción administrativa sensible debe ser auditable