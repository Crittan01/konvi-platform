# Framework de Conectores (patrón de proyecto)

Última actualización: 2026-04-21

## Objetivo

Definir un patrón consistente para integrar proveedores externos sin romper:

- aislamiento multi-tenant
- trazabilidad operativa
- contratos transaccionales

## Patrón base

1. Credenciales por tenant  
- se guardan en `tenant_integrations` o `notification_settings`
- no se modelan como secretos globales si son tenant-scoped

2. Cliente de integración en backend  
- ubicación actual: `services/api/integrations/*` o `services/ai-orchestrator/*`
- validación de input antes de llamar proveedor

3. Endpoints internos tipados  
- exposición vía routers FastAPI (`services/api/routers/*`)
- errores con detalle operativo (sin filtrar secretos)

4. Flujos async cuando aplique  
- colas `pgmq` para eventos críticos (takeover/outbound)
- retries y estados terminales explícitos

## Estado actual por proveedor

- WhatsApp: inbound en connector; outbound en orchestrator (credenciales por tenant).
- Mercado Libre: integrado en `services/api` (OAuth + webhook + listings).
- Aveonline: integrado en `services/api` (cotización, generación de guía y webhook de tracking; único provider de shipping, ADR-0019).
- Telegram: notificaciones por tenant en worker.
