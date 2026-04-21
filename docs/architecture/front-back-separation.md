# Separación Frontend / Backend (runtime)

Última actualización: 2026-04-21

## Principio

La Tenant Console no es barrera de seguridad.  
El contrato real vive en API Gateway + DB (RLS donde aplica) + filtros explícitos por `tenant_id`.

## Mapeo de superficies

| Capa | Ubicación | Rol |
|---|---|---|
| Frontend | `apps/web` | UX, Server Components/Actions, proxies de API |
| Gateway API | `services/api` | reglas de negocio, auth JWT, RBAC, hardening |
| Connector inbound | `services/connector-whatsapp` | entrada de webhooks Meta + persistencia inbound |
| Worker AI | `services/ai-orchestrator` | procesamiento async, colas, envío outbound |
| DB/Auth | Supabase | esquema, RLS, auth, colas (`pgmq`) |

## Contratos relevantes de integración

1. Inbox humano outbound  
- Frontend: `POST /api/conversations/{id}/send` (Next route handler proxy)
- API: `POST /api/v1/conversations/{id}/send`
- Async real: cola `whatsapp_outbound_messages` -> orchestrator -> Meta

2. Shipping quote  
- Frontend: `POST /api/shipping/quote`
- API: `POST /api/v1/shipping/quote`
- Integración: `services/api/integrations/envia_client.py`

3. Marketplace MeLi  
- Frontend: `apps/web/app/dashboard/(channels)/marketplace/*`
- API: routers `marketplace.py`, `integrations.py`, `meli_webhook.py`

## Nota de deployment

En Render Free, el orchestrator corre como servicio web (`server.py` + thread daemon) por limitaciones de plan.  
En plan pago (Starter+), el target recomendado es worker nativo.
