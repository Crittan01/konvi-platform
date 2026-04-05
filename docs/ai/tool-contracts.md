# Tool Contracts

## Objetivo
Definir contratos claros para las herramientas usadas por el AI Orchestrator.

## Reglas generales
- toda tool recibe contexto de tenant
- toda tool valida permisos antes de operar
- toda tool devuelve salida estructurada
- toda tool debe ser auditable

## Tools previstas
- get_product
- get_variant_stock
- get_order_status
- quote_shipping
- search_knowledge
- create_handoff
- draft_reply
- get_marketplace_sync_status