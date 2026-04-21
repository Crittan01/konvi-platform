# Registro de Riesgos

Última actualización: 2026-04-21

## Riesgos activos

| ID | Categoría | Riesgo | Severidad | Mitigación |
|---|---|---|---|---|
| R-01 | Disponibilidad | Limitaciones de Render Free en operación real | Alto | Upgrade a plan pago cuando aplique trigger productivo |
| R-02 | Multi-tenant | Error de scoping con `service_role` puede exponer datos cruzados | Alto | Filtros explícitos por `tenant_id` + tests + revisión continua |
| R-03 | Integraciones | Fallos upstream (Meta/Envia/MeLi) impactan operación | Medio | retries, colas, observabilidad y fallback humano |
| R-04 | Operación | Ausencia de Platform Console obliga soporte asistido | Medio | mantener runbooks y trazabilidad hasta fase 12 |
| R-05 | Runtime Python | Desalineación entre versión objetivo y runtime local puede generar drift | Medio | estandarizar versión antes de release productivo |
| R-06 | Build/Release | `next build` falla local con error genérico de webpack sin traza útil | Medio | aislar causa reproducible y fijar antes de release candidate |

## Riesgos cerrados recientes

- Contratos runtime de conversación unificados.
- OAuth MeLi endurecido (state firmado + anti-replay).
- Outbound humano desacoplado vía cola durable.
- Hardening de writes críticos (RL + idempotencia + observabilidad).
