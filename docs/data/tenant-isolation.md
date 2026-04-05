# Tenant Isolation

## Objetivo
Garantizar aislamiento entre clientes.

## Niveles de aislamiento

### 1. Aislamiento de datos
Todas las entidades sensibles deben asociarse a tenant_id cuando corresponda.

### 2. Aislamiento de permisos
Los permisos deben resolverse por membresía de tenant y rol.

### 3. Aislamiento de storage
Los archivos deben segregarse por tenant en buckets o paths controlados por políticas.

### 4. Aislamiento de integraciones
Cada cuenta de canal o marketplace debe pertenecer explícitamente a un tenant.

### 5. Aislamiento administrativo
Los administradores de plataforma no deben acceder por defecto a datos sensibles de tenant sin justificación y auditoría.

## Estados del tenant
El tenant debe poder tener estados operativos y comerciales, por ejemplo:
- active
- suspended
- pending_setup
- restricted
- disabled

## Casos especiales
- suspensión por no pago
- suspensión por incumplimiento
- tenant en onboarding
- tenant con integraciones desactivadas

## Regla crítica
Subdominio no es seguridad.
La seguridad real vive en Auth + claims + RBAC + RLS + storage policies + auditoría.