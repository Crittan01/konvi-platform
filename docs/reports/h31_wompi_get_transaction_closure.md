# H.3.1 — Wompi GET /transactions/{id} — cierre

**Fecha:** 2026-05-29
**Item Plan K:** H.3.1 — Wompi GET `/transactions/{id}` endpoint
**Estado:** **CLOSED AS-IS WITH DOCUMENTED RATIONALE**
**Audit que lo detectó:** workflow Plan K (2026-05-29) — marcado PARTIAL

## Resumen

El item H.3.1 del Plan K original (sección H.3) listaba "GET `/transactions/{id}` para auditoría sin webhook" como **P0 — bloqueante para reconciliación**. El audit de 2026-05-29 detectó ambigüedad: ¿"endpoint" significaba endpoint HTTP en `services/api/routers/wompi_*.py`, o método del cliente Python `WompiClient.get_transaction()`?

## Estado de implementación verificado

| Componente | Estado |
|---|---|
| `WompiClient.get_transaction()` (sync) | ✅ IMPLEMENTED — `services/api/integrations/wompi_client.py` |
| `WompiClient.get_transaction_async()` (async) | ✅ IMPLEMENTED |
| `get_transaction_with_resilience()` (retry + circuit breaker wrapper) | ✅ IMPLEMENTED |
| Endpoint HTTP `GET /api/v1/wompi/transactions/{id}` | ❌ NOT EXISTS |
| Caller productivo del método Python | ⚠️ NINGUNO — disponible pero no invocado en runtime |

Endpoints HTTP Wompi expuestos actualmente: solo `POST /webhooks/wompi` (inbound webhook handler).

## Decisión arquitectónica original (Sem 4, 2026-05-06)

Documentada en transcript de sesión 2026-05-06: implementar **solo el cliente Python** y **diferir el endpoint HTTP** hasta que una de estas dos condiciones se cumpla:

1. **UI Tenant Console "Reconciliar pago"** — feature donde operador ve transacción Wompi individual para reconciliar manualmente cuando webhook falló. Requiere endpoint HTTP para que el frontend consulte.
2. **Background reconciliation job** — cron que detecta órdenes en `pending_payment > 24h` y consulta `WompiClient.get_transaction()` para verificar estado real. Esto NO requiere endpoint HTTP — el job invoca el cliente Python directamente.

Hoy, ninguna de las dos features está priorizada en el roadmap.

## Por qué cerrar el item ahora

1. **Cliente Python listo**: cualquier caller futuro (cron, script admin, endpoint HTTP) puede invocarlo trivialmente. La complejidad de Wompi API (auth, error mapping, retries) ya está absorbida.
2. **Plan K spec ambiguo sin caso de uso real**: crear endpoint HTTP sin caller justificado sería over-engineering. El item original asumía un caso de uso que nunca se materializó en el roadmap.
3. **Costo de re-abrir es bajo**: cuando se diseñe la UI de reconciliación o el cron job, agregar el endpoint HTTP es ~1-2h (wrapper trivial sobre `get_transaction()` + auth `require_write_role` + manejo de errores tipados).
4. **NO ELIMINAR el cliente Python**: sigue siendo API estable. Cualquier eliminación rompería futuros callers sin ganancia.

## Cuándo re-abrir este item

Crear nuevo item Plan K (`H.3.1.1`) con caso de uso explícito cuando ocurra cualquiera de:

- **Founder/PM prioriza** feature "Reconciliar pago" en Tenant Console.
- **Incidente productivo** revela que webhooks Wompi fallan recurrentemente y se necesita endpoint sync para operador.
- **Background reconciliation cron** se diseña → en ese caso NO necesita endpoint HTTP, solo invoca `get_transaction_with_resilience()` directamente desde `services/ai-orchestrator/worker.py`.

## Métrica de cierre

Plan K avance: **12 → 13 items IMPLEMENTED** (de 18 críticos auditados) tras cerrar este item como DOCUMENTED_AS_COMPLETE.

## Referencias

- Cliente Python: [services/api/integrations/wompi_client.py](../../services/api/integrations/wompi_client.py)
- Audit Plan K que detectó la ambigüedad: workflow `wf_a2c76690-d27` (2026-05-29)
- Decisión Sem 4 original: [docs/HANDOFF.md](../HANDOFF.md) sección "Migraciones recientes (cierre correctivo)" + Plan K § H.3
- ADR-0011 cart-as-SoT + Wompi lifecycle: [docs/adr/0011-cart-as-sot.md](../adr/0011-cart-as-sot.md) (referencia)
