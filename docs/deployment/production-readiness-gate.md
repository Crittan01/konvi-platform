# Gate Formal: Free -> Pago (Production Readiness)

Última actualización: 2026-04-21

Este documento define el criterio formal para decidir el upgrade de infraestructura desde planes Free hacia planes pagos.

## 1) DECISION FINAL

No migrar por calendario.
Migrar solo cuando exista evidencia funcional + operativa de necesidad real.

Regla de activación: **cumplir al menos 2 de 3 triggers** y no tener bloqueadores duros abiertos.

## 2) Triggers Go/No-Go

### Trigger A — Operación real
- Existe al menos 1 tenant real en operación diaria.

### Trigger B — Impacto por limitaciones Free
- Se observa degradación recurrente por Free en flujos críticos:
  - cold starts en web/api/orchestrator
  - latencia inaceptable en Inbox/send/webhook
  - backlog de cola por falta de worker dedicado

### Trigger C — Cierre funcional mínimo
- Checklist funcional de salida completo:
  - inbox/send/status funcionando de forma estable
  - cierre de fases funcionales de Inbox segun matriz de intents
    (`docs/operations/inbox-intents-matrix.md`)
  - runbooks operativos vigentes
  - alertas críticas operativas
  - incidencias P1/P2 controladas

## 3) Bloqueadores duros (si existe cualquiera, no hay GO)

1. Contratos runtime ambiguos o no validados en producción-lab.
2. Secrets/rotación sin cierre documental.
3. Falta de rollback claro de cutover.
4. Integraciones críticas con fallos no controlados (Meta/Aveonline/MeLi/Wompi).
5. Fase A/B de Inbox sin certificar (catalogo variantes + pedidos/shipping).

## 4) Ventana de evidencia mínima

- Ventana recomendada: 14 días consecutivos.
- Fuente de evidencia:
  - Render logs/metrics por servicio
  - Supabase logs/usage/realtime
  - métricas operativas internas (colas, errores, retries)
  - resultados UAT por intents (`docs/operations/inbox-intents-matrix.md`)

## 4.1) Orden funcional previo al gasto (linea de fases)

1. Fase A: respuestas de catalogo completas (incluye variantes) sin invencion.
2. Fase B: estado de pedido + cotizacion/seguimiento de envio con datos backend.
3. Fase C: pagos (Wompi) con sandbox primero y validacion legal/operativa.

Regla: no abrir Fase C sin cierre formal de A y B.

## 5) Scorecard de decisión

Usar esta tabla y completarla antes de aprobar gasto:

| Criterio | Umbral | Resultado real | Estado |
|---|---|---|---|
| Trigger A (tenant real) | >= 1 tenant activo diario | TBD | Pendiente |
| Trigger B (impacto Free) | >= 3 incidentes operativos atribuibles a Free / 14 días | TBD | Pendiente |
| Trigger C (funcional mínimo) | 100% checklist cierre funcional | TBD | Pendiente |
| Bloqueadores duros | 0 abiertos | TBD | Pendiente |

Regla final:
- **GO**: al menos 2 triggers en estado Cumplido + bloqueadores duros = 0.
- **NO-GO**: cualquier otro escenario.

## 5.1) Snapshot actual (2026-04-21)

Evidencia técnica disponible en esta sesión:
- Build frontend: `pnpm --filter web build` ✅
- Tests backend: `python3.11 -m unittest discover` ✅ (42 tests)
- Tests frontend puntuales: `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
- Estado colas `pgmq`:
  - `pgmq.q_human_takeover_notifications`: `0` pendientes
  - `pgmq.q_whatsapp_outbound_messages`: `0` pendientes
- Actividad 14 días (entorno linked):
  - `messages_14d`: `43`
  - `conversations_14d`: `1`
  - `usage_events_14d`: `8`
- Integraciones activas:
  - `envia=connected`, `mercadolibre=connected`, `whatsapp=connected`

Limitación de evidencia:
- No se pudo ejecutar smoke HTTP directo contra URLs Render desde esta VM por restricción DNS del entorno.

Evaluación del gate hoy:

| Criterio | Estado |
|---|---|
| Trigger A (tenant real operativo) | No demostrado con evidencia de negocio en esta sesión |
| Trigger B (impacto Free demostrado) | No demostrado con evidencia operacional en esta sesión |
| Trigger C (cierre funcional mínimo) | Parcial (base técnica OK; faltan cierres funcionales/operativos pendientes en backlog) |
| Bloqueadores duros | Abiertos (pendientes funcionales críticos y validaciones de salida) |

Resultado: **NO-GO** al upgrade pago en este momento.

## 6) Arquitectura objetivo al pasar a pago

1. Mantener `web`, `connector`, `api` como web services.
2. Migrar `konvi-orchestrator` de `type: web` a `type: worker`.
3. Revalidar colas `human_takeover` y `whatsapp_outbound` con worker nativo.

## 7) Plan de cutover (alto nivel)

1. Aprobar presupuesto y plan objetivo (Render + Supabase).
2. Actualizar `render.yaml` (plan por servicio + `orchestrator` worker).
3. Deploy controlado en ventana acordada.
4. Smoke post-cutover:
   - `/health` de servicios
   - inbox + send humano + webhook inbound
   - consumo de colas + retries
5. Monitoreo reforzado 24-48h.

## 8) Rollback

Si falla cualquier validación crítica:
1. Revertir commit/config de `render.yaml`.
2. Restaurar modo anterior de `orchestrator`.
3. Revalidar flujos críticos.

## 9) INTERVENCION HUMANA REQUERIDA

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner + DevOps + Finanzas  
**MOMENTO**: cuando scorecard cumpla criterio GO  
**PASOS DUMMY O GUIADOS**:
1. Completar scorecard con evidencia de 14 días.
2. Aprobar presupuesto mensual tope.
3. Autorizar ejecución de cutover.
4. Ejecutar checklist post-cutover y firma de cierre.
**INSUMOS NECESARIOS**: acceso billing Render/Supabase + reportes operativos.  
**CRITERIO DE EXITO**: infraestructura de pago activa, sin regresiones críticas, con SLO operativo estable.

## 10) VALIDAR EN DOCUMENTACION OFICIAL

- Render Free: https://render.com/docs/free
- Render Background Workers: https://render.com/docs/background-workers
- Render Pricing: https://render.com/pricing
- Supabase billing/cuotas: https://supabase.com/docs/guides/platform/billing-on-supabase
- Supabase Realtime limits: https://supabase.com/docs/guides/realtime/rate-limits
