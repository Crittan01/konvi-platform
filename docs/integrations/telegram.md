# Telegram Integration

## Objetivo
Usar Telegram como canal interno de operación y soporte, no como canal principal del cliente final.

## Casos de uso
- alertas operativas
- aprobaciones rápidas
- notificaciones internas
- fallback operativo
- monitoreo

## Reglas
- exponer solo la información mínima necesaria
- no exponer datos sensibles innecesarios
- vincular acciones a usuarios internos autenticados
- segregar cualquier dato por tenant cuando aplique

## Intervención humana esperada
- creación del bot
- configuración de webhook o modo de conexión
- distribución de acceso a usuarios internos autorizados