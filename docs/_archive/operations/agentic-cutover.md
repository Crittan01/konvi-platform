> **⚠️ ARCHIVADO — 2026-08-03.** Contenido histórico superado, conservado solo como registro. Estado vigente: docs/PLAN.md y .context/01-state.md.

---

# Agentic Cutover — Runbook Operativo

**ADR**: [ADR-0018 Agentic Orchestrator Hybrid](../adr/0018-agentic-orchestrator-hybrid.md).
**Última actualización**: 2026-05-27.

## TL;DR

Activar el agentic orchestrator para un tenant específico:

```bash
python3.11 scripts/agentic_cutover.py --status                   # ver estado actual
python3.11 scripts/agentic_cutover.py --tenant <UUID> --enable   # activar
python3.11 scripts/agentic_cutover.py --tenant <UUID> --disable  # rollback inmediato
```

Sin flags activos = comportamiento legacy idéntico al pre-refactor. **El default es seguro.**

---

## Pre-cutover checklist

Antes de activar agentic FULL en producción para un tenant:

- [ ] Suite tests verde local: `python3.11 -m pytest tests/ -q` (mínimo 2,240 passing).
- [ ] Golden conversations E2E con Gemini real pasan: `python3.11 -m pytest tests/agentic/test_golden_conversations.py -v` (5/5 con `GEMINI_API_KEY` configurada).
- [ ] **Shadow mode 7 días** sobre el tenant target — ver §"Shadow mode" abajo.
- [ ] Análisis de divergencia legacy vs agentic en `agentic_shadow_log` table — ver §"Divergence analysis".
- [ ] Capacity check Gemini API quota (suficiente headroom para 2-3× tool calls/turn del shadow + full del tenant).
- [ ] Avisar al tenant del cambio si es producción real (a veces hay diferencias de estilo que el operator quiere validar).

## Shadow mode (7 días recomendados pre-cutover)

Shadow mode corre el agente **silenciosamente** mientras el legacy responde al cliente. Permite comparar comportamientos sobre tráfico real sin impactar UX.

### Activación

En el deploy del worker (Render env vars o equivalente):

```bash
AGENTIC_SHADOW_ENABLED=true
AGENTIC_SHADOW_TIMEOUT_S=30
```

Reiniciar el worker. A partir de ese momento:

- Legacy sigue respondiendo a cada inbound (sin cambio en UX cliente).
- Agentic corre en paralelo (fire-and-forget) y escribe en `agentic_shadow_log` table.

### Costo esperado shadow

Por turn ~$0.002-0.005 USD adicional (Gemini 2.5 Flash + 2-3 tool calls).
Multiplicado por turns/día del tenant.

Ejemplo: 200 turns/día × $0.003 = **$0.60/día/tenant en shadow** (rolling).
Si shadow corre para todos los tenants (env var es global), multiplicar por count tenants activos.

### Apagar shadow

```bash
# Desetear env var en deploy + reiniciar worker.
AGENTIC_SHADOW_ENABLED=false
```

## Divergence analysis

Después de N días de shadow, consultar `agentic_shadow_log`:

```sql
-- Distribución de tool calls executed (esperado: 1-4 por turn).
SELECT
  tool_calls_executed,
  COUNT(*) AS n,
  AVG(elapsed_seconds) AS avg_latency
FROM agentic_shadow_log
WHERE tenant_id = '<tenant_uuid>'
  AND created_at > now() - interval '7 days'
GROUP BY tool_calls_executed
ORDER BY tool_calls_executed;

-- Turns truncados (agentic se quedó sin budget).
SELECT
  truncated_reason,
  COUNT(*) AS n
FROM agentic_shadow_log
WHERE tenant_id = '<tenant_uuid>'
  AND truncated = true
  AND created_at > now() - interval '7 days'
GROUP BY truncated_reason;

-- Errores del agentic (deberían tender a 0).
SELECT error, COUNT(*) FROM agentic_shadow_log
WHERE tenant_id = '<tenant_uuid>'
  AND error IS NOT NULL
  AND created_at > now() - interval '7 days'
GROUP BY error
ORDER BY 2 DESC;

-- Comparar agentic_outbound vs legacy outbound (mismo conversation_id).
-- legacy outbound vive en messages table; cruzar manualmente.
SELECT
  sl.created_at,
  sl.inbound_text,
  sl.agentic_outbound,
  m.content AS legacy_outbound
FROM agentic_shadow_log sl
JOIN messages m
  ON m.conversation_id = sl.conversation_id
  AND m.direction = 'outbound'
  AND m.created_at BETWEEN sl.created_at AND sl.created_at + interval '60 seconds'
WHERE sl.tenant_id = '<tenant_uuid>'
ORDER BY sl.created_at DESC
LIMIT 50;
```

**Criterios de cutover-ready** (mínimos):

- truncated_rate < 5% (turnos completos sin hit del budget de tools).
- error_rate < 1% (agentic NO crashea en producción).
- avg_latency < 5s P95.
- Divergencia subjetiva (operator review): agentic resuelve al menos tan bien como legacy en los casos observados.

## Cutover (activar agentic FULL)

Cuando los criterios de divergencia se cumplen:

```bash
# Step 1: Activar el tenant.
python3.11 scripts/agentic_cutover.py --tenant <UUID> --enable

# Step 2: Verificar status.
python3.11 scripts/agentic_cutover.py --status

# Step 3: Monitorear primer turn real.
tail -f /var/log/ai-orchestrator.log | grep -E "AGENTIC_FULL|AGENTIC_DISPATCH"

# Step 4: Si algo sale mal:
python3.11 scripts/agentic_cutover.py --tenant <UUID> --disable
# El worker en su próximo polling cycle (≤3s) usa legacy.
```

## Comportamiento por flag combinaciones

| `tenant.agentic_enabled` | env `AGENTIC_SHADOW_ENABLED` | Comportamiento |
|---|---|---|
| `False` (o no seteado) | `false` (o no seteado) | **Legacy** responde. Default. Sin cambios pre-refactor. |
| `False` | `true` | Legacy responde + agentic corre shadow en paralelo + log. |
| `True` | `false` | **Agentic** responde al cliente para este tenant. Otros tenants legacy. |
| `True` | `true` | Agentic responde + shadow ignorado para este tenant (no duplicación). |

## Rollback de emergencia

Si agentic causa problemas en producción para un tenant:

```bash
# Opción 1: disable per-tenant (preferido — rollback parcial).
python3.11 scripts/agentic_cutover.py --tenant <UUID> --disable

# Opción 2: deshabilitar para TODOS los tenants vía SQL.
psql ... -c "
  UPDATE tenant_integrations
  SET meta = jsonb_set(meta, '{agentic_enabled}', 'false')
  WHERE meta->>'agentic_enabled' = 'true';
"

# Opción 3 (extrema): rollback del deploy.
# Branch productiva es phase-0-pre-prod. Agentic vive en
# phase-2-agentic-rewrite. Si el merge a producción tiene problemas,
# revert el merge commit y redeploy.
```

## Migración de datos

**NO se requiere migración de datos del cliente** para activar/desactivar agentic. Tanto legacy como agentic usan las mismas tablas (cart_events, messages, contacts, orders, payments). Cliente puede tener turns en legacy y los siguientes en agentic sin perder estado.

La única tabla nueva es `agentic_shadow_log` (audit silencioso). Migration: `supabase/migrations/20260527000000_agentic_shadow_log.sql`.

## Soporte + escalación

Si durante el shadow o el cutover se detectan bugs:

1. Capturar el turn afectado (`conversation_id` + timestamp).
2. Query `agentic_shadow_log` (si shadow) o `messages` (si full).
3. Verificar `tool_call_log` JSONB — ahí se ve exactamente qué tools invocó el LLM y qué resultaron.
4. Reportar con esa data en issue / Slack para análisis.

NO se debe "parchar" el agentic ad-hoc — el paradigma está diseñado para que comportamiento nuevo emerja de tool descriptions + system_prompt + nuevos tools, NO de detectores tokenizados.
