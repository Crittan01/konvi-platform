---
trigger: always_on
---

# Formato de salida del proyecto

## Objetivo

Mantener respuestas tecnicas compactas, operativas y faciles de ejecutar dentro de este repositorio.

## Regla de estilo

- Responder en formato compacto por defecto.
- Evitar introducciones largas, contexto redundante y texto ornamental.
- Preferir bloques cortos y directos.
- Expandir solo si hay riesgo alto, impacto arquitectonico, seguridad, integraciones externas o cambios irreversibles.

## Formato por tipo de tarea

### Implementacion

Usar este orden:

- objetivo
- decision
- archivos o modulos afectados
- riesgos
- validaciones
- siguiente paso

### Debugging

Usar este orden:

- causa probable
- evidencia
- validacion
- fix propuesto
- riesgo de regresion

### Code review

Usar este orden:

- hallazgo
- impacto
- cambio sugerido
- severidad

### Arquitectura

Usar este orden:

- contexto
- decision
- tradeoffs
- riesgos
- dependencias
- validaciones pendientes

## Regla de compresion

- Ser breve, pero no criptico.
- No omitir datos que afecten seguridad, multi-tenant, permisos, storage, integraciones o auditoria.
- Si una decision depende de proveedor, incluir explicitamente la documentacion oficial a validar antes de cerrar la implementacion.
