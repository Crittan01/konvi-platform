# Connector Framework

## Objetivo
Definir una abstracción común para integraciones externas de canales y marketplaces.

## Motivación
El sistema debe soportar:
- WhatsApp como canal principal
- Telegram interno
- Mercado Libre desde el inicio
- Shopify en futuro
- tienda personalizada en futuro

Para evitar acoplamiento excesivo, cada integración debe implementarse como conector desacoplado.

## Tipos de conectores
### 1. Channel Connectors
Canales conversacionales o de interacción:
- WhatsApp
- Telegram

### 2. Commerce / Marketplace Connectors
Sistemas externos de catálogo, stock, pedidos o publicaciones:
- Mercado Libre
- Shopify
- tienda personalizada futura

## Principios
- cada conector pertenece a un tenant
- cada conector tiene configuración propia
- el core interno define el modelo canónico
- los conectores adaptan entre el modelo interno y el modelo externo
- ningún conector define la verdad del sistema por sí solo

## Entidades recomendadas
- channels
- channel_accounts
- product_channel_mappings
- sync_runs
- sync_errors
- integration_credentials_metadata
- connector_states

## Capacidades del framework
- registrar conectores por tenant
- habilitar/deshabilitar conectores
- almacenar estado de conexión
- almacenar estado de sync
- enrutar eventos inbound
- publicar trabajos outbound
- auditar ejecuciones
- reconciliar divergencias

## Contratos base sugeridos
### Inbound event
Evento recibido desde tercero.
Debe incluir:
- connector_type
- tenant_id
- external_account_id
- event_type
- external_event_id
- received_at
- raw_payload_reference

### Outbound action
Acción hacia tercero.
Debe incluir:
- connector_type
- tenant_id
- operation_type
- target_resource
- payload_reference
- idempotency_key

## Reglas
- toda integración debe documentar auth
- toda integración debe documentar webhooks/notificaciones si existen
- toda integración debe documentar mapeos
- toda integración debe documentar reconciliación
- toda integración debe documentar intervención humana requerida