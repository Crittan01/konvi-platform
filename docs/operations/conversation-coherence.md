# Coherencia conversacional — estrategia + herramientas

**Objetivo:** que la lógica de conversación del bot sea *totalmente acorde* de
forma **sistémica**, no bug-por-bug. Disparador: bugs recurrentes en los bordes
de estado (variante falsa, total sin envío, no reconocer add-product en checkout)
cuyo patrón común es que el modelo **per-estado** (Rev.109) optimiza el *happy
path* de cada estado, pero las conversaciones reales son **no-lineales** (el
cliente modifica el carrito en PAYMENT, pregunta por catálogo en checkout, va
"hacia atrás").

## Estrategia (4 palancas)

1. **Harness adversarial dinámico** (detección) — escenarios no-lineales que el
   bot LIVE maneja, verificando coherencia bot-vs-DB turn-a-turn sobre la
   respuesta REAL. Cada bug reportado → un escenario permanente. *Implementado.*
2. **Observabilidad por turno** (acelerador) — trace estructurado que hace
   visible la decisión del bot. *Implementado.*
3. **Reconciliación de estado intra-turno** (raíz estructural) — tras mutar el
   carrito, re-evaluar el estado y forzar la corrección. *Pendiente.*
4. **Contrato de invariants completo** (enforcement proactivo) — enumerar todas
   las verdades transaccionales y cerrar huecos antes de que sean bugs. *Pendiente.*

## Herramienta 1 — Harness de coherencia (palanca 1)

```bash
# Requiere stack local vivo (connector :8000 + orchestrator + DB)
python3.11 scripts/uat/coherence_scenarios.py --list           # ver escenarios
python3.11 scripts/uat/coherence_scenarios.py --scenario add_in_checkout
python3.11 scripts/uat/coherence_scenarios.py                  # todos
```

- **Dinámico:** lee la respuesta REAL del bot cada turno (no scripts estáticos)
  y aplica assertions de coherencia bot-vs-DB.
- **Núcleo puro reutilizable:** `scripts/uat/coherence_assertions.py` — verdades
  transaccionales como funciones puras (no total stale, total incluye envío,
  total == carrito, menciona ambas variantes, no expone internals). Testeadas en
  `tests/test_a11_coherence_assertions.py` (corren sin stack).
- **Añadir un escenario** = una entrada en `SCENARIOS` (cada turno: mensaje +
  lista de assertions). Cada bug nuevo se codifica aquí → nunca regresa.

## Herramienta 2 — Observabilidad por turno (palanca 2)

El dispatcher emite un trace estructurado por turno (1 línea greppable):

```
[AGENTIC_TRACE] conv=<id8> state=<FSM> tools=[...] invariant=<name:outcome> rewrote=<bool>
```

Cuando un escenario falla o algo se ve raro:

```bash
grep "AGENTIC_TRACE" <orchestrator.log> | grep conv=<id8>
```

muestra, por turno: estado FSM resuelto, tools invocados, invariant que
intervino y si hubo rewrite — la causa al instante (antes había que leer código).

## Cómo crece esto

Cada conversación reportada con incoherencia →
1. reproducir como escenario en `SCENARIOS`,
2. confirmar que falla (rojo),
3. arreglar (prompt/resolver/invariant/tool-subset),
4. confirmar verde + dejar el escenario como regresión permanente.
