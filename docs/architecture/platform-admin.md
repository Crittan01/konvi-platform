# Platform Admin

## Objetivo
Definir el rol y límites del superadmin o administración de plataforma.

## Principio central
El superadmin de plataforma no debe tener acceso libre e indiscriminado a la información sensible de los tenants.

## Responsabilidades válidas
- onboarding técnico de tenants
- soporte operativo de la plataforma
- activación/desactivación de features
- monitoreo global de salud del sistema
- revisión de errores de integraciones
- administración de planes y configuración general

## Accesos que deben restringirse
- ver conversaciones completas de tenants sin razón justificada
- consultar inventario o precios de tenants por comodidad
- acceder a documentos internos de un tenant sin necesidad de soporte justificada
- ejecutar acciones destructivas sin trazabilidad

## Reglas
- todo acceso excepcional debe quedar auditado
- preferir soporte con contexto mínimo necesario
- separar claramente admin de tenant y admin de plataforma
- no usar el rol de plataforma como bypass informal de RLS sin justificación y auditoría

## Recomendación operativa
Diseñar flujos de soporte donde:
- el tenant autoriza o solicita soporte
- el acceso excepcional queda registrado
- el alcance del acceso sea temporal o limitado