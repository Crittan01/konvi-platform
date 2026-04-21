# Matriz de Intents Inbox (Certificacion Funcional)

Ultima actualizacion: 2026-04-21

Este documento define que intents debe resolver Inbox en automatico, cuales deben escalarse y en que fase se habilitan.

## DECISION FINAL

Implementar por fases:
1. Fase A: completitud de respuestas de catalogo con variantes (sin inventar).
2. Fase B: estado de pedido + cotizacion de envio desde herramientas backend.
3. Fase C: pagos (Wompi) solo despues de cerrar A y B con evidencia estable.

## VALIDAR EN DOCUMENTACION OFICIAL

- WhatsApp Cloud API (politicas y envio): https://developers.facebook.com/docs/whatsapp
- Wompi ambientes/llaves: https://docs.wompi.co/docs/colombia/ambientes-y-llaves/
- Wompi eventos por ambiente: https://docs.wompi.co/docs/colombia/eventos/
- Wompi tokens de aceptacion: https://docs.wompi.co/docs/colombia/tokens-de-aceptacion/

## RIESGO

- Alto riesgo operacional si se promete "responder todo" sin tools transaccionales.
- Riesgo de precision en catalogo cuando el producto tiene multiples variantes.
- Riesgo legal/comercial si pagos se habilitan sin flujo de aceptacion/documentacion.

## IMPACTO OPERATIVO

- Reduce reprocesos en takeover humano y evita respuestas ambiguas.
- Permite certificar Inbox con criterios de negocio y no solo tecnicos.
- Ordena el roadmap para pasar a infraestructura paga cuando exista evidencia real.

## INTERVENCION HUMANA REQUERIDA

**INTERVENCION HUMANA REQUERIDA**: Si
**RESPONSABLE**: Product Owner + Operacion Comercial + Tech Lead
**MOMENTO**: antes de marcar cierre funcional de Inbox para salida productiva
**PASOS DUMMY O GUIADOS**:
1. Aprobar la clasificacion por intent (`auto` vs `humano`).
2. Definir SLA esperado por intent (tiempo maximo de respuesta).
3. Aprobar criterios de exito por fase (A/B/C).
4. Firmar acta de cierre de cada fase con evidencia de pruebas.
**INSUMOS NECESARIOS**: matriz de intents, casos UAT, tenant piloto
**CRITERIO DE EXITO**: intents criticos con estado `certificado` y trazabilidad de evidencia

## Matriz (estado actual -> objetivo)

| Intent | Estado actual | Modo actual | Objetivo | Fase objetivo |
|---|---|---|---|---|
| Saludo/contexto basico | Implementado | Auto | Mantener | A |
| Consulta de producto (titulo) | Implementado | Auto | Mantener | A |
| Precio de producto | Implementado parcial mejorado | Auto | Cerrar precision por variante | A |
| Stock disponible | Implementado parcial mejorado | Auto | Cerrar precision por variante | A |
| Consulta por variante (color/talla/modelo) | Implementado mejorado (match exacto asistido) | Auto/Humano | Cerrar UAT y ajuste fino de ambiguedad | A |
| Politicas del negocio (FAQ) | Dependiente de KB | Auto/Humano | Garantizar cobertura minima por KB activa | A |
| Estado de pedido | Gap | Humano | Responder con datos transaccionales reales | B |
| Cotizacion de envio | Gap | Humano | Cotizar via backend shipping tool | B |
| Seguimiento de envio | Gap parcial | Humano | Integrar consulta de tracking en tool | B |
| Solicitud de pago/link de pago | No implementado | Humano | Integrar Wompi con guardrails y legalidad | C |
| Reclamo/disputa sensible | Implementado | Humano (takeover) | Mantener escalamiento obligatorio | A |

## Criterios de certificacion por fase

### Fase A - Catalogo completo con variantes

1. No inventar precio/stock cuando falte dato.
2. Resolver producto + variante con consulta estructurada backend.
3. Escalar a humano cuando no exista coincidencia confiable.
4. Pruebas UAT sugeridas: minimo 30 casos, exito >= 95% en intents de catalogo.

### Avance tecnico actual (2026-04-21)

1. Contexto de catalogo en orquestador ahora incluye:
   - rango de precio (`price_min/price_max`)
   - stock total por producto
   - desglose de variantes legibles (atributos/SKU) con limite operativo
2. Prompt del orquestador muestra variantes explicitas para mejorar respuestas.
3. Analisis de variante en query:
   - detecta consultas de variante (color/talla/SKU)
   - inyecta coincidencias exactas cuando existen
   - fuerza instruccion de no inventar y escalar cuando no hay match exacto
4. Memoria deterministica corta para ambiguedad:
   - en follow-ups de variante, detecta producto en contexto desde historial reciente
   - usa ese contexto para resolver variante o pedir precision sin inventar
5. Evidencia tecnica:
   - `python3.11 -m unittest tests/test_catalog_tool_variants.py tests/test_orchestrator_catalog_prompt.py tests/test_orchestrator_takeover.py tests/test_whatsapp_parser_context.py` -> OK (15 tests)
6. Estado: implementacion tecnica cerrada para match asistido + memoria corta; pendiente cierre funcional UAT.

### Fase B - Shipping y pedidos

1. Estado de pedido debe venir de fuente transaccional (no LLM).
2. Cotizacion de envio debe usar endpoints backend existentes.
3. Errores externos (carrier/API) deben quedar explicitos y escalarse.
4. Pruebas UAT sugeridas: minimo 25 casos, exito >= 95%.

### Fase C - Pagos (Wompi)

1. Sandbox primero, luego produccion.
2. Tokens de aceptacion y eventos por ambiente obligatorios.
3. No confirmar pagos por texto libre; solo por estado transaccional validado.
4. Pruebas UAT sugeridas: minimo 20 casos, exito >= 98% en estado de pago.

## Checklist de ejecucion inmediata (proximo sprint)

1. Congelar esta matriz como contrato operativo de Inbox.
2. Abrir backlog tecnico de Fase A (variantes + precision catalogo).
3. Definir suite de pruebas UAT por intent en tenant piloto.
4. No habilitar fase de pagos hasta cierre formal de Fase B.
