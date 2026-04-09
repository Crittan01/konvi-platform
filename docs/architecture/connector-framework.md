# Connector Framework — Arquitectura de Conectores

Última actualización: 2026-04-09

---

## Propósito

Framework modular que permite agregar integraciones con canales externos, marketplaces y servicios (WhatsApp, Mercado Libre, Shopify, Envia, etc.) como módulos independientes con una interfaz estándar.

Cada conector:
- Tiene su propio directorio en `services/connector-{nombre}/`
- Maneja `tenant_id` en **toda** operación — nunca cruza datos entre tenants
- Está documentado con sus capacidades, auth y variables de entorno

---

## Estado de conectores

| Conector | Servicio | Estado | Notas |
|----------|----------|--------|-------|
| WhatsApp Cloud API (Meta) | `services/connector-whatsapp` | ✅ Funcional | HMAC-SHA256 ok, tenant resolver ok. API v21.0 |
| Mercado Libre | `services/connector-mercadolibre` | ❌ Pendiente | Fase 8 |
| Shopify | `services/connector-shopify` | ❌ Futuro | Sin fecha |
| Telegram Bot (interno) | No implementado | ❌ Pendiente | Fase 8+ |
| Envia Shipping | No implementado | 📋 Diseñado | Ver docs/integrations/courier-envia.md |

---

## Interfaz estándar de conector

Todo conector debe exponer, según su tipo:

```python
class BaseConnector:
    tenant_id: UUID
    
    async def health_check(self) -> dict: ...

class CatalogConnector(BaseConnector):
    async def sync_catalog(self) -> list[ProductSchema]: ...

class OrderConnector(BaseConnector):
    async def get_orders(self, since: datetime) -> list[OrderSchema]: ...
    async def update_order_status(self, order_id: str, status: str) -> bool: ...

class MessagingConnector(BaseConnector):
    async def send_message(self, recipient: str, message: str) -> bool: ...

class ShippingConnector(BaseConnector):
    async def get_rates(self, origin: AddressSchema, destination: AddressSchema, parcels: list) -> list[RateSchema]: ...
    async def create_label(self, rate_id: str, shipment: ShipmentSchema) -> LabelSchema: ...
    async def get_tracking(self, tracking_number: str) -> TrackingSchema: ...
    async def create_pickup(self, pickup: PickupSchema) -> PickupConfirmSchema: ...
```

---

## Conector WhatsApp (`services/connector-whatsapp`) — ✅ Funcional

- **Dirección**: Inbound (recibe mensajes) + Outbound (envía desde el Orchestrator)
- **Auth**: `META_APP_SECRET` (HMAC-SHA256) + `META_ACCESS_TOKEN` (Graph API)
- **Endpoints Meta usados**:
  - Verificación challenge: `GET /{phone-number-id}/messages`
  - Envío: `POST /{WHATSAPP_PHONE_ID}/messages` (Graph API v21.0)
- **Validación de firma**: ✅ HMAC-SHA256 implementado (`X-Hub-Signature-256`)
- **Tenant resolver**: ✅ Por `meta_waba_id` real (no por hardcode)
- **Variables de entorno**: `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`, `WHATSAPP_PHONE_ID`
- **URL Render**: `https://commerce-ops-connector.onrender.com`

---

## Conector Mercado Libre (`services/connector-mercadolibre`) — ❌ Pendiente (Fase 8)

- **Auth**: OAuth 2.0 con refresh token **por tenant** (cada tenant tiene su propia app MeLi)
- **Capacidades planeadas**:
  - Sync de catálogo ML → tabla `products` + `product_variations`
  - Notificaciones de nuevas órdenes via IPN (webhooks ML)
  - Actualización de stock bidireccional
- **Documentación oficial**: `https://developers.mercadolibre.com.ar/`
- **Precaución**: Revisar documentación oficial antes de implementar (tokens, scopes, rate limits)

---

## Conector Envia — Shipping/Courier — 📋 Diseñado

Ver `docs/integrations/courier-envia.md` para diseño completo.

- **Auth**: API Key por tenant (o global según plan de Envia)
- **Capacidades diseñadas**:
  - Shipping API: quotes, labels, tracking, pickups, manifests, cancellations
  - Queries API: carriers, services, country/state, pickup options, validaciones previas
- **Acoplamiento prohibido**: No conectar Envia directamente al LLM
- **Toda cotización, pickup o label** debe ir por el backend/connector — nunca generada por el LLM

---

## Conector Telegram — ❌ Pendiente

- Uso interno: alertas de sistema, notificaciones operacionales
- No es canal de atención al cliente
- Implementar en Fase 8+

---

## Reglas para implementar nuevos conectores

1. Crear directorio en `services/connector-{nombre}/`
2. `main.py` con FastAPI si tiene endpoints HTTP propios
3. `requirements.txt` con dependencias exactas
4. `README.md` con: capacidades, auth, variables de entorno, limitaciones
5. Manejar `tenant_id` en **toda** operación — nunca cruzar datos entre tenants
6. Documentar en este archivo y actualizar `docs/architecture/modules.md`
7. Revisar documentación oficial del proveedor antes de implementar
8. No usar el conector como fuente de verdad de datos del negocio — solo como canal de integración

---

## Documentos relacionados

- `docs/integrations/whatsapp.md` — Detalle de integración WhatsApp
- `docs/integrations/mercadolibre.md` — Detalle de integración MeLi
- `docs/integrations/courier-envia.md` — Diseño del connector Envia
- `docs/architecture/modules.md` — Estado de todos los módulos
