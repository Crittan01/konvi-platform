# Platform Admin

## Objetivo
Definir el plano administrativo de la plataforma, separado lógicamente del plano del tenant.

## Principio
No se implementará inicialmente como una app separada.
Se implementará dentro de la misma app web, usando rutas, layouts y permisos distintos.

## Espacios lógicos de la aplicación

### Tenant Space
Rutas y vistas para operación del cliente:
- catálogo
- stock
- pedidos
- inbox
- conocimiento
- logística
- integraciones del tenant

### Platform Space
Rutas y vistas para administración de la plataforma:
- tenants
- estados comerciales
- suspensión/reactivación
- feature flags
- salud de integraciones
- métricas globales
- auditoría de soporte
- operaciones internas

## Roles de plataforma
- platform_owner
- platform_admin
- platform_support
- platform_billing

## Capacidades de plataforma
- ver tenants
- suspender tenants
- reactivar tenants
- bloquear acceso por estado comercial
- ver consumo y estado general
- ver estado de conectores
- ver errores globales
- administrar banderas de funcionalidad
- realizar soporte auditado

## Restricción crítica
Los roles de plataforma no deben acceder por defecto al detalle sensible de datos de tenant sin trazabilidad y justificación.

## Consecuencia arquitectónica
No se necesita apps/admin-portal desde el día 1.
La separación se hace por:
- auth
- roles
- rutas
- layout
- auditoría