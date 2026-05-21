# ADR-0017 — Orchestrator Strangler-Fig Refactor

**Estado:** ACTIVO (en ejecución).
**Fecha:** 2026-05-21.
**Branch:** `phase-1-orchestrator-refactor`.
**Punto de partida:** `phase-0-pre-prod` @ commit `78f6ac6`.

## Contexto

`services/ai-orchestrator/orchestrator.py` ha crecido a **10,262 LOC** en una sola unidad. La función `build_and_run_orchestration` tiene **3,589 LOC**. La lógica de decisión está dispersa en:

- 124 funciones top-level (helpers, detectores, builders, formateadores).
- 13 bypasses pre/post-LLM con guards multiplicativos anti-interferencia.
- 17 detectores `_detect_*` con listas hardcoded de tokens (frágiles a variantes coloquiales).
- 12 funciones parseando `history` como SoT secundario (compitiendo con cart-as-SoT, ADR-0011).
- 10 invocaciones dispersas de `_build_order_summary_text` (cada sitio carga contact/cart por separado → riesgo de stale).
- 28 lecturas dispersas de `get_cart_with_items`.
- 23 listas/sets hardcoded de markers.
- 24 imports dentro de funciones (acoplamiento implícito).

Cada bug del UAT founder en últimas iteraciones (shipping_phone perdido, 3 sérums agregados, alucinación de gramaje, PII pre-cart, LLM componiendo en estados transaccionales) es **síntoma del mismo problema raíz**: la lógica determinística está dispersa y compite con la libertad del LLM en cada turn.

El producto puede ir a producción con 5 tenants piloto en estado actual. Pero **no es ejecutable** sobre este monolito el plan I (multi-agente, storefront, channel registry, cupones avanzados) sin que cada feature añada +1000 LOC de bypasses nuevos.

## Decisión

Refactorizar `orchestrator.py` mediante **strangler-fig de 8 semanas** sobre branch dedicada `phase-1-orchestrator-refactor`. NO se hace big-bang rewrite. El monolito vive durante todo el refactor; cada semana se extrae UNA capa, los call-sites del monolito se reemplazan por llamadas a la capa extraída.

Target final: orchestrator.py ≤1,500 LOC como pipeline de 10 stages con contratos explícitos.

Documento arquitectónico completo: [`docs/architecture/orchestrator-refactor-target.md`](../architecture/orchestrator-refactor-target.md).

### Stages del pipeline

1. **LoadContextStage** — carga contact, cart, catalog, kb, history.
2. **SafetyGatesStage** — Meta 24h, domain filter, content safety, escalation.
3. **InboundIntentStage** — clasificadores consolidados (BuyingIntent, CartAction, PIIUpdate, VariantConfirmation, Escalation).
4. **ToolDispatchStage** — tools determinísticos pre-LLM (shipping_quote, image_send, order_status).
5. **FSMResolverStage** — display_state determinístico (reusa `fsm/resolver.py`).
6. **StateHandlerStage** — los 13 bypasses unificados en handlers per-state.
7. **LLMStage** — solo si stages 2-6 no resolvieron. Prompt modular.
8. **OutputValidatorStage** — anti-hallu invariants unificados.
9. **PIIPersistStage** — USYNC extractions + reload contact fresh.
10. **DispatchOutboundStage** — envía + marca processed + emite cart_events.

### Estructura de datos central: `TurnContext`

Estructura inmutable que fluye por el pipeline. Cada stage recibe `TurnContext` y produce uno nuevo (no muta el input). Esto elimina la clase de bugs donde `contact_record` queda stale entre operaciones de un mismo turn.

## Consecuencias

### Positivas

- Cada bug futuro afectará **una sola stage o handler**, no se propagará.
- Cada feature nueva (multi-agente, storefront) será una stage o handler nuevo, no más bypasses.
- Onboarding técnico futuro: 3-4 semanas → 1-2 semanas.
- Test pyramid balanceado: unit tests por stage + behavioral golden tests por flow.
- `orchestrator.py` legible end-to-end como pipeline declarativo.
- Plan A.2 (objetivo histórico ≤500 LOC) viable post-refactor.

### Negativas

- **8 semanas de feature freeze** sobre `phase-0-pre-prod` (excepto P0 bugs).
- Riesgo de regresión silente si tests no capturan algún edge case (mitigado por suite 2,184 + smoke UAT semanal).
- Coordinación con hotfixes producción durante refactor (rebasing semanal).

### Neutras

- **Comportamiento externo del bot NO cambia**. Cliente debe percibir idéntico (o mejor por consistencia).
- Cart-as-SoT (ADR-0011), FSM canónico, Wompi lifecycle, Habeas Data: no se tocan.
- Tests existentes (2,184): todos deben seguir verdes sin modificación de assertions.

## Alternativas consideradas

### A. Status quo + parches puntuales

Seguir cazando bugs reportados por founder UAT en el monolito. Costo bajo a corto plazo. **Rechazada** porque cada bug del último mes lleva progresivamente más esfuerzo (guards multiplicativos), y plan I es inejecutable sobre este monolito.

### B. Big-bang rewrite

Reescribir `orchestrator.py` desde cero en 2-3 semanas. **Rechazada** por riesgo de regresión inaceptable: 2,184 tests cubren comportamiento actual; rewrite los rompería de golpe y la depuración sería intratable.

### C. Strangler-fig 8 semanas (ELEGIDA)

Extracciones semanales con monolito vivo durante todo el proceso. Tests verdes después de cada extracción. Smoke UAT semanal. Permite hotfixes de producción durante refactor (rebasing).

## Criterios de éxito

Documentados en `docs/architecture/orchestrator-refactor-target.md` §8. Resumen:

- orchestrator.py ≤1,500 LOC al cierre Sem 8.
- `build_and_run_orchestration` ≤300 LOC.
- Suite tests verde (≥2,400 tests).
- UAT S1-S26 dual-mode 100% PASS.
- Smoke UAT real cliente nuevo + cliente conocido = flujo perfecto.
- Comportamiento externo idéntico al pre-refactor.

## Plan operativo

| Semana | Entrega |
|---|---|
| 1 | State Handler Layer (12 handlers + dispatcher) — los 13 bypasses unificados |
| 2 | Intent Classification Layer (5 classifiers, lexicons consolidados) |
| 3 | Output Validator Layer (anti-hallu unificado) |
| 4-6 | Prompt Builder modular (`prompt/blocks/`) |
| 7 | Cart Operations Layer (`load_turn_cart_view` único) + LLM stage formal |
| 8 | Pipeline runner final + cierre |

## Branching

- **`phase-1-orchestrator-refactor`** (branch dedicada para el refactor).
- **`phase-0-pre-prod`** sigue siendo la branch productiva con monolito activo.
- Hotfixes producción → `phase-0-pre-prod` + rebase semanal a `phase-1-orchestrator-refactor`.
- Merge `phase-1-orchestrator-refactor` → `phase-0-pre-prod` solo al cierre Sem 8 con TODOS los criterios done.

## Backup

**Git ES el backup completo.** Cada commit preserva el estado. No se hace copia filesystem.

- Estado pre-refactor: commit `78f6ac6` en `phase-0-pre-prod`.
- Rollback completo si necesario: `git checkout phase-0-pre-prod` (intocado).
- Rollback parcial dentro del refactor: `git reset --hard <commit>` en branch refactor.

## Referencias

- Doc arquitectónico target: [`docs/architecture/orchestrator-refactor-target.md`](../architecture/orchestrator-refactor-target.md).
- Plan A.2 histórico (≤500 LOC objetivo): plan estratégico §A.2.
- ADR-0011 cart-as-SoT (invariante preservado).
- ADR-0006 (orchestrator modular strangler — versión expandida en ADR-0017).
