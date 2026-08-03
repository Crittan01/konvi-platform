# Preguntas Abiertas

Última actualización: 2026-04-21

| ID | Pregunta | Estado | Bloquea |
|---|---|---|---|
| OQ-P01 | Arquitectura Platform Console (misma app o app separada) | Pendiente crítico | Fase 12 completa |
| OQ-PRICING-01 | Modelo comercial final por plan/capability | Pendiente | salida productiva comercial |
| OQ-INFRA-01 | Trigger exacto de upgrade pago (fecha/tenant objetivo/SLA) | En ejecución (gate formal documentado) | readiness productiva |
| OQ-ENVIA-01 | Estrategia final de webhooks y reconciliación Envia | RESUELTA 2026-08-02 — Envia eliminado del runtime (rev. 109, ADR-0019); shipping = Aveonline único (webhook Rev. 108 implementado; pendiente solo polling backup) | — |
| OQ-INBOX-01 | Criterio final de certificación por intents (A/B/C) para declarar Inbox \"completo\" | En ejecución (matriz creada) | salida productiva |
| OQ-PAY-01 | Secuencia final para pagos (Wompi) y owner operativo de conciliación | Pendiente | fase de pagos conversacionales |

## Regla de cierre

Cuando una pregunta se cierre:
1. documentar decisión en `docs/research/validated-decisions.md`
2. actualizar `.context/01-state.md` y roadmap/riesgos afectados
