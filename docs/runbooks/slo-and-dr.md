# Runbook — SLOs, Error Budgets y Disaster Recovery (DR)

> Objetivo: definir **objetivos de servicio medibles** (SLO), su **presupuesto de
> error**, y los procedimientos de **recuperación ante desastre** (RTO/RPO) para la
> plataforma. Cierra el gap del `production-readiness-gate` que pedía "SLO operativo
> estable" sin definirlo.
>
> **Estado de los targets:** los valores de SLO/RTO/RPO de este documento son una
> **PROPUESTA inicial a ratificar por el founder** (no hay historial de métricas aún).
> Se recalibran con datos reales tras ~30 días.
>
> **Complementa (no duplica):**
> - `docs/deployment/rollout-and-rollback.md` — mecánica de deploy/rollback.
> - `docs/legal/incident-response.md` — respuesta a incidentes con datos personales (Ley 1581).
> - `docs/deployment/environments.md` — topología dev/prod.

---

## 1) Alcance y arquitectura

4 servicios en Render (plan Starter, always-on) + Supabase Pro:

| Servicio | Rol | Internet-facing | Criticidad |
|---|---|---|---|
| `konvi-connector` | Webhook inbound WhatsApp (Meta) | Sí | **Crítico** (entrada del bot) |
| `konvi-api` | API Gateway + webhooks Wompi/MeLi/Aveonline/Telegram | Sí | **Crítico** (money-path) |
| `konvi-orchestrator` | Worker AI + colas + crons de reconciliación | No (worker) | **Crítico** (procesa el bot) |
| `konvi-web` | Tenant Console (Next.js) | Sí (`app.konvi.co`) | Alto (operación, no bot) |

Dependencias externas: Supabase (DB/Auth/Realtime), Meta WhatsApp Cloud API, Wompi,
Aveonline, Gemini (LLM).

---

## 2) SLOs (propuesta a ratificar)

SLI = indicador medido; SLO = objetivo sobre el SLI; ventana = **28 días** rolling.

| Servicio | SLI | SLO propuesto | Fuente de medición |
|---|---|---|---|
| connector | Disponibilidad del `/health` + tasa de webhooks WhatsApp procesados sin 5xx | **99.5%** | Render health check + logs (5xx greppable) |
| api | Disponibilidad `/health` + éxito de webhooks money-path (Wompi) | **99.5%** | Render health check + logs |
| api | Latencia p95 de endpoints de la consola | **< 800 ms** | logs por request (medición propia pendiente — fase 12) |
| orchestrator | Latencia p95 por turno del bot (inbound → outbound) | **< 6 s** | logs por turno |
| orchestrator | Tasa de turnos del bot sin error no-manejado | **99.0%** | logs (excepciones ERROR greppables) |
| web | Disponibilidad de `app.konvi.co` (200/307) | **99.5%** | Uptime check + logs |

> **Money-path (Wompi) — SLO reforzado:** 0 órdenes pagadas sin fulfillment por
> webhook perdido **detectadas sin señal**. La detección se cubre con los reconcilers
> del worker + alertas (ver §5 y el gap abierto de reconciliación APPROVED-perdido).

### Cómo se mide (hoy)
- **Logs estructurados** (stdout; Render los retiene): errores y señales greppables
  (`[WOMPI]`, `[AGENTIC_*]`, `[WORKER]`, …) en los 4 servicios. Sin error-tracking
  externo desde S8 (2026-08-17); la observabilidad propia llega en la fase 12.
- **Render**: health checks (`/health` en backends, `/` en web) — reinicia el
  contenedor si falla; los eventos de deploy/health quedan en el dashboard.
- **Pendiente (mejora):** un uptime-check externo (p.ej. cron que cURLea los `/health`
  y alerta) para medir disponibilidad de forma independiente de Render. Hoy el
  health-watcher se corre manualmente durante deploys.

---

## 3) Error budget

Para un SLO de disponibilidad **99.5%** en 28 días:

- Presupuesto de downtime = 0.5% × 28 d ≈ **3 h 22 min / 28 días**.
- Para **99.0%** (turnos del bot) ≈ **6 h 43 min / 28 días** de turnos con error.

**Política de budget:**
- Budget **sano** (> 25% restante) → deploys normales, se puede tomar riesgo de features.
- Budget **bajo** (< 25%) → congelar features no críticas; priorizar estabilidad hasta
  recuperar budget.
- Budget **agotado** → **freeze**: solo fixes de confiabilidad + post-mortem obligatorio.

---

## 4) RTO / RPO (objetivos de recuperación)

| Escenario | RPO (pérdida de datos máx.) | RTO (tiempo de recuperación máx.) |
|---|---|---|
| Deploy defectuoso (código) | 0 (sin pérdida de datos) | **< 15 min** (rollback git → Render redeploy) |
| Caída de un servicio Render | 0 | **< 10 min** (redeploy / restart) |
| Corrupción/pérdida de datos en Supabase | **PITR** (ver §6 — objetivo: minutos) | **< 1 h** (restore) |
| Región Render/Supabase caída | 0–PITR | **best-effort** (dependemos del proveedor; sin multi-región hoy) |

> Los RTO/RPO de datos dependen de las capacidades del plan **Supabase Pro** (backups
> diarios + PITR). **VALIDAR EN DOCUMENTACIÓN OFICIAL** las ventanas exactas de
> retención/PITR del plan contratado antes de ratificar (no asumir números).

---

## 5) Detección y alertas

Orden de detección de un incidente:

1. **Logs estructurados** — excepciones y spikes de error greppables en los 4
   servicios (Render los retiene). *Pendiente*: alerting propio (fase 12, Platform
   Console) → canal del founder.
2. **Render** — health check falla → reinicio automático + evento en dashboard.
3. **Reconcilers del worker** (money-path) — emiten `logger.critical`/métricas ante
   descuadres (p.ej. `paid_orders_protected_from_cancel`, `STUCK refund void`).
4. **Reporte de tenant/cliente** — última línea (a evitar).

> **Gap conocido (money-path):** un pago **APPROVED cuyo webhook nunca llegó** hoy se
> detecta solo si ya existe un `payment` local approved; si no, la orden se cancela a
> los 35 min sin señal automática. Cierre pendiente (requiere capturar el
> `transaction_id` del redirect — Wompi no permite consultar por `reference`). Ver la
> decisión de diseño abierta.

---

## 6) Procedimientos de DR

### 6.1 Rollback de un deploy defectuoso
Ver `docs/deployment/rollout-and-rollback.md`. Resumen:
```bash
# production apunta al último commit bueno. Revertir el merge malo en develop y
# re-desplegar, o forzar production al commit bueno previo:
git push origin <sha-bueno>:production --force-with-lease
```
Render (autoDeploy) reconstruye. Verificar salud con el health-watcher (§7).
**CRITERIO DE ÉXITO:** los 4 servicios responden 200/307 y el error rate vuelve a baseline.

### 6.2 Servicio Render caído
- Render redeploya solo ante fallo de health check. Si no recupera:
  Dashboard → servicio → **Manual Deploy** (último deploy exitoso) o **Restart**.
- Si es OOM del build (web): ver nota `NODE_OPTIONS`/memoria en `render.yaml`.

### 6.3 Incidente de datos en Supabase (restore)
> **INTERVENCIÓN HUMANA REQUERIDA** — RESPONSABLE: founder.
1. **NO** escribir sobre datos potencialmente corruptos. Poner los servicios en modo
   seguro si aplica (pausar el worker: `WORKER_ENABLED`/escalar a 0 si existe).
2. Supabase Dashboard → Database → **Backups / Point-in-Time Recovery** → elegir el
   punto previo al incidente → restore.
3. **INSUMOS:** timestamp del incidente (de los logs), confirmación de alcance.
4. **CRITERIO DE ÉXITO:** integridad verificada (conteos de `orders`/`payments`
   coherentes) + los servicios reconectan sin errores.
5. Post-restore: correr el harness anti-drift local NO aplica a datos; validar con
   queries de conteo y una prueba UAT mínima.

### 6.4 Rotación de credencial comprometida
Vault per-tenant (Meta/Wompi/Aveonline/Telegram) + secrets de plataforma (Render env).
Ver `docs/adr/0025` (Vault ownership). Rotar en el proveedor → actualizar Vault/Render →
redeploy. Los secretos que se hayan expuesto en canales inseguros se rotan siempre.

---

## 7) Verificación de salud (post-incidente / post-deploy)

```bash
for u in https://app.konvi.co \
         https://konvi-api.onrender.com/health \
         https://konvi-connector.onrender.com/health \
         https://konvi-orchestrator.onrender.com/health; do
  printf "%-52s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$u")"
done
# Esperado: web 307 (redirect a login), backends 200.
```
Complementar con: logs (error rate vuelve a baseline) + una conversación UAT mínima
del bot (inbound → outbound) para confirmar el hot-path end-to-end.

---

## 8) Post-mortem (obligatorio si se agota el error budget o hay incidente money-path)
Plantilla mínima: (1) timeline; (2) impacto (tenants/órdenes/dinero); (3) causa raíz;
(4) detección (¿cuánto tardó y por qué?); (5) acciones correctivas con dueño y fecha;
(6) ¿cómo lo prevenimos? Guardar en `docs/reports/postmortem-<fecha>.md`.

---

## INTERVENCIÓN HUMANA REQUERIDA (para ratificar este runbook)
- **RESPONSABLE:** founder.
- **PASOS:** (1) ratificar/ajustar los SLO/RTO/RPO propuestos; (2) validar en la doc de
  Supabase Pro las ventanas reales de backup/PITR; (3) decidir el canal de alertas
  propias (fase 12); (4) decidir si se agrega un uptime-check externo.
- **CRITERIO DE ÉXITO:** SLOs medibles con alertas activas + DR probado al menos una vez
  (restore de Supabase en un entorno de prueba).
