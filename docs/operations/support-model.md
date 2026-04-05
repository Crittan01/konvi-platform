# Support Model

## Objetivo
Definir el modelo de soporte y acceso administrativo.

## Roles de plataforma
- platform_owner
- platform_admin
- platform_support
- platform_billing

## Principios
- el soporte debe ser auditable
- el acceso extraordinario debe quedar registrado
- el soporte no debe tener visibilidad plena por defecto de datos sensibles
- el soporte debe trabajar con el menor privilegio posible

## Casos de soporte previstos
- tenant suspendido
- error de integración
- sync bloqueado
- problemas de acceso
- incidente de media
- error de configuración

## Requisito
Toda acción de soporte relevante debe registrarse en audit_logs o support_access_logs.