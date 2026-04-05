# Runbooks

## Objetivo
Definir respuestas operativas ante fallos o incidentes previsibles del sistema.

## Runbook 1: Webhook de WhatsApp no llega
### Síntomas
- conversaciones nuevas no aparecen
- mensajes salientes sí funcionan pero no entran mensajes
- falta de eventos recientes

### Revisar
- configuración del webhook en Meta
- reachability del endpoint
- validación de firma/token si aplica
- logs del servicio API
- estado del deployment
- errores HTTP

### Acciones
1. verificar endpoint
2. revisar logs
3. confirmar configuración del webhook
4. reintentar evento desde proveedor si existe capacidad
5. escalar a soporte técnico interno

## Runbook 2: Media de WhatsApp no se descarga
### Síntomas
- el mensaje existe pero el archivo no
- URLs expiran antes de descarga
- errores de permisos o token

### Revisar
- proceso asincrónico de media
- estado de queue
- token del canal
- logs del worker
- storage policies

### Acciones
1. revisar cola
2. revisar worker
3. reintentar descarga
4. verificar expiración y autenticación
5. registrar incidente si persiste

## Runbook 3: Sync de Mercado Libre falla
### Síntomas
- stock no coincide
- publicación no se actualiza
- errores repetidos de sync

### Revisar
- credenciales
- autorización de la app
- mapping producto/variación
- logs del connector
- sync_runs y sync_errors
- estado de notificaciones

### Acciones
1. identificar tenant afectado
2. revisar último sync_run
3. detectar si es error recuperable
4. reintentar con control
5. si no se resuelve, dejar en estado degradado visible en panel

## Runbook 4: Fuga o sospecha de cruce entre tenants
### Síntomas
- usuario ve datos de otro tenant
- media incorrecta
- resultados RAG cruzados

### Revisar
- RLS
- claims en JWT
- queries
- filtros de tenant
- storage path
- tool contracts

### Acciones
1. detener acceso afectado
2. revisar auditoría
3. identificar alcance
4. corregir filtro/política
5. documentar incidente y mitigación

## Runbook 5: Worker atascado o cola creciendo
### Síntomas
- jobs acumulados
- retrasos visibles
- embeddings o syncs no terminan

### Revisar
- worker
- queue
- payloads fallidos
- retries
- cron jobs
- logs

### Acciones
1. verificar proceso worker
2. revisar jobs en error
3. detectar patrón
4. reiniciar o escalar worker si aplica
5. registrar postmortem si es incidente repetido

## Regla
Todo runbook debe actualizarse cuando se identifique un incidente nuevo o una causa raíz relevante.