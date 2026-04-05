# Guardrails

## Objetivo
Definir límites y validaciones para que el AI Orchestrator opere de forma segura, controlada y compatible con un producto multi-tenant real.

## Principio general
El LLM ayuda a interpretar, redactar y decidir qué herramienta usar, pero no puede inventar ni convertirse en autoridad sobre datos críticos del negocio.

## El orquestador SÍ puede
- interpretar intención
- decidir qué tool consultar
- reformular información obtenida de tools
- resumir
- generar borradores
- sugerir respuestas a agentes
- consultar knowledge base mediante RAG
- escalar a humano cuando detecte límites o riesgo

## El orquestador NO puede
- inventar stock
- inventar precios
- inventar estados de pedidos
- alterar datos transaccionales sin una tool explícita autorizada
- romper aislamiento multi-tenant
- acceder a datos de otro tenant
- omitir validaciones de permisos
- ejecutar acciones administrativas sin control

## Guardrails funcionales
1. Toda pregunta sobre datos operativos debe intentar resolverse con tools o DB.
2. Si no hay dato confiable, debe reconocer la limitación.
3. Si la confianza es baja o el caso es sensible, debe escalar a humano.
4. Debe operar con contexto de tenant y rol.
5. Toda tool debe tener contrato estructurado.
6. Toda respuesta crítica debe poder trazarse a tool o fuente.

## Casos que deben escalar a humano
- reclamos complejos
- fraude o sospecha de fraude
- cambios manuales excepcionales
- devoluciones especiales
- incidencias logísticas no resueltas
- respuestas fuera de política
- conflictos de stock
- ambigüedad alta
- fallos reiterados de integración

## Riesgos a controlar
- alucinación
- prompt injection
- exfiltración de datos
- tool misuse
- respuestas fuera de política
- filtrado insuficiente por tenant
- sobreconfianza en RAG

## Validaciones mínimas
- validación previa de tenant
- validación previa de permisos
- validación de esquema de entrada de tools
- validación de esquema de salida
- logging de invocación de tools
- fallback seguro

## Fallbacks
- responder que no se pudo confirmar el dato
- derivar a humano
- dejar ticket o handoff
- registrar error o warning operativo

## Regla obligatoria
Ningún guardrail se considera “válido por intuición”; toda implementación real debe contrastarse con documentación oficial del modelo y del framework o SDK utilizado.