# Integración Envia (estado real)

Última actualización: 2026-04-22

## Estado actual

- Fase inicial implementada (`quote` + `history`).
- Fase 2 parcial implementada (label/tracking/pickup/cancel) con feature flag.
- Inbox Fase B1: orquestador consume `shipping/quote` para responder cotización en chat con `highlights`.
- Normalización runtime de país endurecida para quote (`Colombia` / `COL` / `CO` -> `CO`) antes de construir payload hacia Envia.
- En Inbox, errores upstream de Envia se registran en logs pero no se exponen en texto técnico al cliente final.
- En Inbox, origen se toma estrictamente de `tenants.shipping_origin` (sin fallback implícito por texto libre).
- En Inbox, el paquete de cotización se estima con datos de inventario (`product_variations.weight_kg/length_cm/width_cm/height_cm`) y cantidad inferida del mensaje; si faltan datos usa defaults controlados.
- En Inbox, si el contexto conversacional tiene múltiples productos plausibles, solicita confirmación del producto antes de cotizar para evitar falsos positivos.
- Respuesta de cotización en chat: bloque operativo (`origen -> destino`, paquete estimado, opción más económica / más rápida) con CTA para continuidad de compra.
- Webhooks async de Envia: pendientes.

## Implementación real en código

- Cliente: `services/api/integrations/envia_client.py`
- Router: `services/api/routers/shipping.py`
- UI: `apps/web/app/dashboard/(sales)/shipping/shipping-quote-form.tsx`
- Persistencia: tabla `shipments`

## Endpoints activos

- `POST /api/v1/shipping/quote`
- `GET /api/v1/shipping/history`
- `POST /api/v1/shipping/{shipment_id}/label` (flag)
- `POST /api/v1/shipping/tracking` (flag)
- `POST /api/v1/shipping/pickup` (flag)
- `POST /api/v1/shipping/cancel` (flag)

Feature flag: `ENVIA_PHASE2_ENABLED`.

### Contrato de respuesta en `POST /api/v1/shipping/quote` (runtime)

Además de `shipment_id` y `rates`, la API retorna `highlights`:

- `highlights.cheapest`: tarifa con menor `total_price`.
- `highlights.fastest`: tarifa con menor tiempo de entrega usando:
  1. `delivery_date` (fecha más temprana) cuando existe.
  2. `delivery_estimate` parseable (horas/días) cuando no hay `delivery_date`.

Si no hay señal de velocidad confiable (`delivery_date` ni `delivery_estimate` parseable), `fastest` se omite para evitar inferencias.

## Modelo de credenciales

- Token Envia por tenant en `tenant_integrations.credentials.api_token`.
- No usar token global de Envia por servicio.

## Reglas

1. El LLM no inventa cotizaciones ni estados de envío.
2. Shipping responde solo con datos reales del backend.
3. Si faltan datos de dirección/paquete, se solicita información o se escala a humano.

## Pendientes reales

1. Webhooks de estado Envia.
2. Validaciones carrier-específicas de fase 2.
3. Source dinámico de geografía Envia (state/city) para frontend.
4. Observabilidad de fallos por carrier/tenant.

## Referencias

- `docs/architecture/connector-framework.md`
- `docs/architecture/front-back-separation.md`
- `docs/data/schema.md`
- Envia Shipping API Overview: https://docs.envia.com/docs/envia-shipping-api-introduction
- Envia Quote Shipments (`POST /ship/rate/`): https://docs.envia.com/reference/quote-shipments
- Envia Core Workflow: https://docs.envia.com/docs/core-workflow
