# Connector Framework

## Objetivo
Definir una abstracción común para integraciones de canales y marketplaces.

## Conectores previstos
- WhatsAppConnector
- MercadoLibreConnector
- ShopifyConnector
- CustomStoreConnector

## Responsabilidades comunes
- autenticación/configuración por tenant
- mapeo de recursos externos a entidades internas
- sincronización
- manejo de errores
- auditoría
- estado de conexión
- reconciliación

## Reglas
- cada conector pertenece a un tenant
- no mezclar datos entre tenants
- cada conector debe registrar estado y errores
- cada conector debe permitir activación/desactivación