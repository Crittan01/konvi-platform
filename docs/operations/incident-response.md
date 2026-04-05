# Incident Response

## Objetivo
Definir una respuesta mínima ante incidentes técnicos u operativos.

## Clasificación propuesta

### Severidad 1
Incidente crítico que afecta:
- producción completa
- múltiples tenants
- pérdida de acceso general
- fuga o riesgo alto de datos
- caída de inbox principal
- fallo grave de autenticación/autorización

### Severidad 2
Incidente alto que afecta:
- un tenant importante
- una integración crítica
- procesos de sync bloqueados
- media no procesada de forma sistemática
- fallos prolongados en workers o cron

### Severidad 3
Incidente medio:
- errores acotados
- problemas de UI
- retrasos parciales de jobs
- fallos recuperables sin impacto general

## Flujo de respuesta
1. detectar incidente
2. clasificar severidad
3. contener impacto
4. registrar incidente
5. comunicar estado
6. mitigar
7. restaurar
8. documentar post-incidente

## Casos previstos
- webhook de WhatsApp no procesado
- expiración o fallo de descarga de media
- errores de Mercado Libre sync
- RLS mal configurada
- tenant suspendido incorrectamente
- storage policy incorrecta
- cron job fallando
- worker atascado
- duplicación de mensajes o sync

## Requisitos
- todo incidente relevante debe quedar documentado
- toda intervención manual debe registrarse
- todo incidente de seguridad debe activar revisión de auditoría