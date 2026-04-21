# Integración Envia (estado real)

Última actualización: 2026-04-21

## Estado actual

- Fase inicial implementada (`quote` + `history`).
- Fase 2 parcial implementada (label/tracking/pickup/cancel) con feature flag.
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
