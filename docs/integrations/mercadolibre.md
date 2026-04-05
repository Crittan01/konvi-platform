# Mercado Libre Integration

## Objetivo
Sincronizar productos, variantes, stock y estado de publicaciones usando APIs oficiales y notificaciones oficiales.

## Principios
- Supabase como fuente operativa principal
- mapeo producto interno -> item/variation/user product
- sync bidireccional controlado
- reconciliación periódica
- auditoría de sync
- manejo de conflictos e idempotencia

## Reglas
- no asumir compatibilidad sin revisar docs oficiales
- no depender solo de webhooks/notificaciones
- guardar estado de sync y errores por tenant

## Intervención humana esperada
- app de Mercado Libre
- credenciales
- autorización del seller
- suscripción/configuración de notificaciones