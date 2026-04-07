# Connector Framework — Arquitectura de Conectores

## Propósito

Framework modular que permite agregar integraciones con marketplaces y canales externos (Mercado Libre, Shopify, etc.) como módulos independientes que exponen una interfaz estándar.

## Estado de Conectores

| Conector | Servicio | Estado |
|---|---|---|
| WhatsApp Cloud API (Meta) | `services/connector-whatsapp` | 🟡 Parcial — fix pendiente |
| Mercado Libre | `services/connector-mercadolibre` | ❌ Pendiente (Fase 8) |
| Shopify | `services/connector-shopify` | ❌ Futuro |
| Telegram Bot (interno) | No implementado aún | ❌ Futuro |

## Interfaz Estándar de Conector

Todo conector debe exponer:

```python
# Interfaz base esperada de cada conector
class BaseConnector:
    tenant_id: UUID
    
    async def sync_catalog(self) -> list[ProductSchema]: ...
    async def get_orders(self, since: datetime) -> list[OrderSchema]: ...
    async def send_message(self, recipient: str, message: str) -> bool: ...
    async def health_check(self) -> dict: ...
```

## Conector WhatsApp (`services/connector-whatsapp`)

- **Dirección**: Inbound (recibe mensajes) + Outbound (envía desde el Orchestrator)
- **Auth**: Meta App Secret (HMAC) + META_ACCESS_TOKEN
- **Endpoints Meta usados**:
  - Verificación: `GET /{phone-number-id}/messages` 
  - Envío: `POST /{WHATSAPP_PHONE_ID}/messages` (Graph API v21+)
- **Variables de entorno**: `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`, `WHATSAPP_PHONE_ID`

## Conector Mercado Libre (`services/connector-mercadolibre`) — Planificado

- **Auth**: OAuth 2.0 con refresh token por tenant
- **Capacidades planeadas**:
  - Sync de catálogo ML → tabla `products`
  - Notificaciones de nuevas órdenes via IPN (webhooks ML)
  - Actualización de stock
- **Documentación oficial**: `https://developers.mercadolibre.com.ar/`

## Reglas para Implementar Nuevos Conectores

1. Crear directorio en `services/connector-{nombre}/`
2. `main.py` con FastAPI si tiene endpoints HTTP
3. `README.md` con capacidades, auth, y variables de entorno requeridas
4. Debe manejar `tenant_id` en **toda** operación — nunca cruzar datos entre tenants
5. Documentar en este archivo y actualizar `docs/architecture/modules.md`
