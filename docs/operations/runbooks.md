# Runbooks

## Objetivo
Definir respuestas operativas estandarizadas a fallas comunes.

## Runbooks mínimos previstos

### 1. Webhook de WhatsApp fallando
- verificar disponibilidad del endpoint
- revisar logs de validación
- revisar secrets/configuración
- revisar respuesta rápida del handler
- revisar cola de trabajos posteriores

### 2. Sync de Mercado Libre con errores
- revisar sync_runs
- revisar sync_errors
- verificar credenciales y autorización
- validar payload esperado
- revisar reconciliación pendiente

### 3. Media de WhatsApp no descargada
- verificar job de descarga
- verificar expiración de URL
- revisar permisos/token
- revisar storage target
- registrar retry controlado

### 4. Falla de RLS o acceso denegado
- revisar rol/claims
- revisar tenant_members
- revisar policy de la tabla
- validar contexto del request
- nunca desactivar RLS como atajo

### 5. Worker atascado
- revisar cola
- revisar retries
- revisar job payload
- revisar errores repetidos
- detener retry infinito si existe bug de negocio

### 6. Tenant onboarding incompleto
- revisar subdominio
- revisar creación de tenant
- revisar roles iniciales
- revisar integraciones pendientes
- revisar checklist humana

## Regla
Cada runbook real debe evolucionar con pasos exactos, responsables y criterios de cierre.