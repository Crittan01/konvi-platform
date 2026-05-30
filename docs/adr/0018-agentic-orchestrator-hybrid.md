# ADR-0018 — Agentic Orchestrator with Hybrid LLM Tool-Use

**Estado:** ACTIVO (Fase 0 MVP en ejecución).
**Fecha:** 2026-05-22.
**Branch:** `phase-2-agentic-rewrite`.
**Punto de partida:** `phase-0-pre-prod` @ commit `1b2ec16`.

## Contexto

El orchestrator monolito actual (10,200+ LOC en `orchestrator.py`) opera bajo el paradigma "LLM redactor + Python decide TODO". Este paradigma tiene limitaciones estructurales que se manifiestan en bugs runtime recurrentes que NO se arreglan con más parches:

1. **Detectores tokenizados frágiles**: 17 funciones `_detect_*` con listas hardcoded. Cada variante coloquial nueva (vendeme/peudes vender/regálame X) requiere actualizar listas. Patrón infinito.

2. **LLM ciego al estado real**: el LLM compone texto basado solo en lo que ve del prompt. Si Python falla en silencio (e.g., un detector tier-2 retorna [] cuando debió retornar matches), el LLM **afirma cosas que no pasaron**.

Caso runtime motivador (conv `4cb7477d`, 2026-05-22):
- Cliente: "1 Jabón Coco y 2 Lavanda" (sin gramaje).
- Bot: "Listo, 1 Coco y 2 Lavanda. ¿Cotizamos envío?"
- Cart real: 1 proposal Lavanda qty=2. **Coco no existe. Variante no resuelta. Pedido roto.**

Cada bug del founder UAT en últimas iteraciones es síntoma del mismo problema raíz: **el LLM no puede ejecutar acciones — solo describirlas — y Python no entiende intent semántico sin listas que se desactualizan**.

## Decisión

Pivotar al paradigma **agentic LLM con tool-use nativo + Python guardrails para invariantes críticos**.

### Qué se delega al LLM agentic (Gemini 2.5 function calling)

- Comprensión del intent del cliente (sin detectores).
- Decisión de qué tool invocar con qué argumentos.
- Composición de respuestas con contexto completo.
- Manejo del flujo conversacional (preguntas de variante, modificaciones, etc.).

### Qué permanece en Python (NO delegable)

- **Wompi payment lifecycle** (ADR-0011): create_payment_link, webhook signature, idempotency.
- **Habeas Data compliance** (Ley 1581 + ADR-0003): consent audit log, PII access log.
- **RLS + tenant isolation**: TenantScopedClient, service_role guards.
- **Anti-hallucination invariants**: validación post-LLM contra cart real.
- **Database operations**: el LLM NUNCA ejecuta SQL. Solo invoca tools que internamente usan supabase-py.

Documento arquitectónico completo: [`docs/architecture/agentic-orchestrator.md`](../architecture/agentic-orchestrator.md).

## Alternativas consideradas

### A. Status quo + parches puntuales (RECHAZADA)

Seguir cazando bugs reportados por founder UAT con más detectores. Cada bug nuevo añade 50-200 LOC al monolito. Costo bajo a corto plazo, deuda exponencial.

### B. Refactor strangler-fig 8 semanas (ABANDONADA — tag `archive/phase-1-strangler-fig-sem1` @ commit `acf2592`)

Organizar el monolito en pipeline de stages + state handlers. Llega a orchestrator.py ≤1,500 LOC en 8 semanas. PERO **mismo paradigma** (LLM redactor + Python decide). Bugs como el de hoy seguirán apareciendo en casos borde nuevos.

### C. Full agentic rewrite (RECHAZADA)

Rewrite total sin guardrails Python para invariantes. Compliance (Habeas Data, Wompi) imposible de delegar al LLM. Riesgo legal + financiero inaceptable.

### D. Hybrid agentic (ELEGIDA)

LLM agentic para flow + cart/shipping. Python para invariantes críticos. Reduce código 60-70% sin sacrificar compliance.

## Estrategia de migración

NO big-bang. Estrategia shadow + cutover gradual:

| Fase | Duración | Entrega |
|---|---|---|
| 0 — MVP funcional | 1-2 sem | 8 tools + agentic loop + tests golden |
| 1 — Shadow mode | 1 sem | Producción dual-write: legacy responde, agentic loggea silenciosamente |
| 2 — Cutover por tenant | 1 sem | Flag `agentic_enabled` per tenant, activación gradual |
| 3 — Deprecación legacy | 1 sem | Eliminación del monolito cuando 0 bugs reportados |

## Consecuencias

### Positivas

- **Reducción de código 60-70%**: de 10,200 LOC → ~3,500-4,000 LOC total.
- **Adaptabilidad**: nuevos comportamientos no requieren código nuevo (el LLM razona sobre tools existentes).
- **Coherencia LLM-state**: el LLM ve resultados reales de tools, no puede mentir sobre cosas que no ejecutó.
- **Onboarding técnico**: 1-2 semanas vs 3-4 semanas actuales.
- **Compliance preservado**: invariantes Python intactos como guardrails.

### Negativas

- **Costo LLM 2-3x**: más tool calls por turn. Mitigación: cache catalog en prompt + temperature=0 para reducir variabilidad.
- **Latencia +1-2s P95**: multi-turn tool calling. Mitigación: streaming + parallel tool calls cuando posible.
- **Testing change**: de asserts unitarios a behavioral golden conversations.
- **Non-determinismo controlado**: temperature=0 + system_prompt riguroso + invariantes Python.

### Neutras

- **Comportamiento externo del bot**: debería ser **mejor** (menos bugs de detectores), no peor.
- **Cart-as-SoT** (ADR-0011): NO cambia. Tools de cart escriben cart_events.
- **Frontend**: cero cambios.

## Criterios de éxito

Documentados en `docs/architecture/agentic-orchestrator.md` §8.

Cierre Fase 0 (MVP):
- 8 tools implementados con Pydantic schemas.
- 5 casos golden conversation pasan.
- Tests unit ≥80% cobertura por tool.
- Latencia P95 ≤5s con 2-3 tool calls promedio.

Cierre Fase 2 (Cutover total):
- Tenants piloto 100% en agentic.
- 0 regresiones en compliance.
- Founder UAT exitoso end-to-end.

## Branching

- **`develop`** integra el trabajo de `phase-2-agentic-rewrite` (mergeada 2026-05-30 via PR #13).
- **`main`** anclada en rev. 103 (último estado certificado Habeas Data); se mueve al cumplir bloqueantes humanos V.3-V.21.
- **Strangler-fig refactor (Sem 1.1-1.3, 2026-05-21)**: tag `archive/phase-1-strangler-fig-sem1` @ commit `acf2592`. Branch `phase-1-orchestrator-refactor` eliminada post-pivot — el tag preserva el commit referenciado para trazabilidad. Los 4 handlers extraídos (`READY_FOR_SUMMARY`, `NEEDS_CONSENT`, etc.) no aplican a la arquitectura agentic actual; el aprendizaje del intento queda documentado en este ADR.

## Referencias

- Doc arquitectónico target: [`docs/architecture/agentic-orchestrator.md`](../architecture/agentic-orchestrator.md).
- Caso motivador: conv `4cb7477d` 2026-05-22 (bot dijo "Listo" sin cart real).
- ADR-0011 Cart-as-SoT (invariante preservado).
- ADR-0003 Habeas Data (invariante preservado).
- ADR-0017 Strangler-fig refactor (pausado en favor de ADR-0018).
- Gemini function calling docs: https://ai.google.dev/gemini-api/docs/function-calling
