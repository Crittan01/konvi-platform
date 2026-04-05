# RAG

## Objetivo
El módulo de RAG permite que el sistema consulte conocimiento semiestructurado del negocio de cada tenant para responder mejor en soporte, ventas y operación, sin convertir al LLM en fuente de verdad transaccional.

## Qué sí entra al RAG
- fichas descriptivas extendidas de productos
- políticas de cambios y devoluciones
- preguntas frecuentes
- scripts de atención
- manuales operativos
- documentos PDF del negocio
- guías de transporte o cobertura de carriers
- lineamientos internos de servicio al cliente
- conocimiento comercial reutilizable

## Qué NO entra al RAG
- stock actual
- precio final vigente
- disponibilidad final
- estado real del pedido
- permisos de usuario
- estados de sincronización críticos
- decisiones administrativas
- datos que deban salir de tablas transaccionales o servicios internos

## Principio central
RAG complementa, no reemplaza:
- SQL
- APIs internas
- tools del orquestador
- reglas de negocio

## Modelo técnico
- embeddings almacenados en pgvector dentro de Postgres
- filtrado obligatorio por tenant
- documentos versionables
- reindexación controlada
- separación entre documento original y chunks

## Pipeline propuesto
1. Ingesta del documento
2. Normalización
3. Extracción de texto
4. Chunking
5. Generación de embeddings
6. Almacenamiento por tenant
7. Indexación
8. Recuperación con filtros
9. Envío del contexto al orquestador

## Chunking
La estrategia exacta debe definirse con base en documentación y pruebas, pero el objetivo es:
- chunks coherentes semánticamente
- metadatos por fuente
- referencia a documento y tenant
- trazabilidad de origen

## Filtrado obligatorio
Toda búsqueda debe filtrar como mínimo por:
- tenant_id
- estado del documento
- tipo de documento si aplica
- versión activa si aplica

## Reindexación
Debe existir mecanismo para:
- reindexar por documento
- reindexar por tenant
- desactivar documentos
- invalidar chunks viejos
- detectar errores de embedding

## Evaluación mínima esperada
- precisión de recuperación en FAQs frecuentes
- ausencia de cruces entre tenants
- trazabilidad de fuentes recuperadas
- fallback seguro cuando no haya suficiente contexto

## Riesgos principales
- prompt injection desde documentos
- mezclar conocimiento obsoleto con vigente
- recuperación de chunks de otro tenant
- confiar en RAG para preguntas que requieren datos transaccionales

## Regla obligatoria
Toda implementación de RAG debe consultar documentación oficial vigente de:
- Supabase / pgvector
- proveedor de embeddings/modelo
- mecanismo real de extracción/ingesta que se use