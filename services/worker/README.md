# services/worker — PLACEHOLDER VACÍO

**Estado**: Directorio vacío. No hay implementación ni decisión formal.

**No documentado en ningún doc del proyecto.** Existe como placeholder.

**Propósito potencial**: Worker de procesamiento asíncrono dedicado:
- Procesamiento de colas de mensajes (pgmq, Redis, etc.)
- Generación masiva de embeddings para RAG
- Batch processing de órdenes o inventario
- Exportaciones CSV pesadas

**Estado actual**: El único worker en producción es `services/ai-orchestrator`, que corre
como `type: web` en Render con el OrchestratorWorker en un daemon thread (workaround por plan Free).

Si se migra a Render Starter, el orchestrator pasaría a `type: worker` y este directorio
podría usarse para separar responsabilidades si hay más workloads de background.

**No está en `render.yaml`. No se despliega.**
