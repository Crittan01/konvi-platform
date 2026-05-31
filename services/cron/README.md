# services/cron — PLACEHOLDER VACÍO

**Estado**: Directorio vacío. No hay implementación ni decisión formal.

**No documentado en ningún doc del proyecto.** Existe como placeholder.

**Propósito potencial**: Tareas programadas que necesiten correr en intervalos:
- Refresh masivo de tokens OAuth (MeLi, Envia)
- Reportes periódicos por tenant
- Cleanup de datos temporales
- Alertas de stock bajo vía Telegram

**Estado actual**: Las tareas periódicas del sistema corren como:
- Polling del AI Orchestrator (daemon thread en `konvi-orchestrator`)
- No hay más jobs programados

**Cuándo implementar**: Cuando una tarea programada no pueda resolver con el polling
del orchestrator y justifique un servicio dedicado.
**No está en `render.yaml`. No se despliega.**
