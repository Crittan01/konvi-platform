# Render Free -> Plan Pago (criterio vigente)

Última actualización: 2026-04-21

## Decisión vigente

El upgrade a plan pago debe ejecutarse cuando estemos cerca de salida a producción o cuando exista bloqueo operativo real en Free.

Esto coincide con el criterio del proyecto: no gastar antes de tiempo, pero tampoco salir a producción con limitaciones que afecten operación real.

## Base oficial (Render docs, verificación 2026-04-21)

- Render documenta que Free tiene limitaciones importantes y no debe usarse para producción real.
- Free web services pueden spin-down por inactividad (~15 min) y reactivarse con latencia apreciable.
- El tipo `background worker` existe como servicio dedicado para procesos continuos sin tráfico entrante.
- Free web services no pueden abrir tráfico saliente por puertos SMTP típicos (`25`, `465`, `587`), lo cual impacta email directo.

## Señales de trigger para upgrade

1. Hay tenant real listo para operar.
2. Cold starts o disponibilidad impactan flujos críticos (Inbox/webhook/outbound).
3. Se requiere worker nativo para orchestrator.
4. Se necesita soporte/SLA superior al plan Free.

Gate formal operativo:
- `docs/deployment/production-readiness-gate.md`

## Cambios técnicos esperados al migrar

1. Ajustar `plan` por servicio en `render.yaml`.
2. Migrar `commerce-ops-orchestrator` de `type: web` a `type: worker`.
3. Cambiar `startCommand` del orchestrator a `python3 main.py`.
4. Revalidar health, colas y tiempos de respuesta end-to-end.

## Riesgo si no se migra a tiempo

- degradación por cold starts en picos o inactividad
- latencia operacional en flujos de cliente y soporte
- mayor fragilidad para operación comercial real

## Validación oficial requerida

Antes de ejecutar compra/upgrade:
- revisar pricing y límites actuales directamente en docs oficiales de Render
- confirmar compatibilidad de tipo worker y condiciones de plan
- confirmar costo vigente por tipo de instancia objetivo

Referencias oficiales:
- https://render.com/docs/free
- https://render.com/docs/background-workers
- https://render.com/pricing
