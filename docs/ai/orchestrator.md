# AI Orchestrator

## Objetivo
El AI Orchestrator asiste en atención y operación, pero no reemplaza la verdad transaccional del sistema.

## Responsabilidades
- interpretar intención del usuario
- decidir qué tool usar
- consultar conocimiento vía RAG cuando corresponda
- generar borradores de respuesta
- escalar a humano cuando corresponda

## Lo que NO puede decidir
- stock final
- precio final
- estado real del pedido
- permisos de usuario
- disponibilidad logística final
- autorizaciones administrativas

## Tools previstas
- get_product
- get_variant_stock
- get_order_status
- quote_shipping
- search_knowledge
- create_handoff
- draft_reply
- get_marketplace_sync_status

## Reglas
- toda tool debe operar con contexto de tenant
- toda salida debe ser estructurada
- debe existir validación previa y posterior
- debe existir fallback seguro