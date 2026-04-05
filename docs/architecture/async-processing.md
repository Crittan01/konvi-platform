# Async Processing Architecture

## Objetivo
Separar correctamente las operaciones rápidas del request path y los procesos pesados o lentos.

## Principio
Toda tarea que:
- dependa de terceros (ej: Mercado Libre, Meta),
- requiera notificaciones o webhooks tolerantes a fallos masivos,
- requiera retry idempotente,
- procese media,
- genere embeddings,
debe salir del request path principal.

## Base tecnológica
- **FastAPI Endpoint (Recolector)**: Como "dumb receiver" para webhooks temporales de alta concurrencia; inyecta rápido a la cola sin ejecutar lógica de negocio.
- **Supabase Queues / pgmq**: Colas relacionales durables, nativas junto a Postgres para transaccionalidad segura.
- **Render Background Workers**: Procesadores asíncronos en colas limitando rate memory y concurrencia.
- **Postgres DB Locks**: Fuente de estado combinando la cola con `FOR UPDATE SKIP LOCKED` para safety concurrency.

## Resoluciones de Concurrencia
- **Webhooks de Mercado Libre y Orders**: Los webhooks inbound no ejecutan lógica. Guardan el `external_event_id` en `pgmq`. El Background Worker procesa ordenadamente la cola filtrada por `tenant_id` o de a lotes (BATCH), anulando lockeos circulares (deadlocks) en el Inventario Transaccional.

## Tipos de trabajo asíncrono

### 1. Media processing
- descarga asíncrona de WhatsApp y validación de proxy storage target quotas.
### 2. Knowledge processing
- carga de documentos PDF largos y vectorización (embeddings_generate).
### 3. Marketplace sync
- sync_runs de Mercado Libre serializado para anular deadlocks transaccionales de sku concurrentes.
### 4. Operación Batch
- compresión general y retries de envíos caídos de mensajería (Dead Letter Queue management).
