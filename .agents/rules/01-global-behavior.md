# Regla: Comportamiento Global del Agente

1. **Documentación oficial primero**: Antes de implementar cualquier integración o decisión técnica, validar en docs oficiales. No asumir cómo funciona una API externa.
2. **No magic LLM**: El LLM nunca es fuente de verdad de stock, precios, pedidos, shipping, tracking ni estados transaccionales.
3. **Producción real**: No atajos de seguridad, no hardcodes de tenant, no demos — diseñar para producción.
4. **Trazabilidad**: Todo cambio importante reflejado en `.md`. Código y documentación sincronizados.
5. **Orden de trabajo**: Claridad funcional/visual → Backend correspondiente → Implementación.

Ver `CLAUDE.md` para reglas completas.
