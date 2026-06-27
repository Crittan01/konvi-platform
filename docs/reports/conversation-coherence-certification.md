# Certificación — Coherencia conversacional del Inbox

**Fecha:** 2026-06-26 · **Commit certificado:** `6f2455fe` (main = develop) · **Tenant live:** KAIU

## Veredicto

**NO es 100%.** Se certifica al nivel **"implementación correcta + cableada + testeada
unitariamente + deployada (CI verde) + verificada en vivo para los flujos core"**. NO se
certifica "cobertura E2E exhaustiva sin huecos de borde". La distinción es deliberada y honesta.

## Evidencia

### 1. Validación dura (determinística)
| Dimensión | Resultado |
|---|---|
| Suite pytest | **3070 passed**, 16 skipped, 21 subtests |
| Aislamiento multi-tenant (lint AST, ADR-0025) | **0 gaps** |
| Ruff | 145 (< baseline 202) |
| CI (`validate.sh --ci` + Next build) | **success** |

### 2. Auditoría adversarial (9 agentes, refutando cada palanca)
- Encontró **2 BLOQUEANTES reales** → cerrados: gate `requires_requote` movido al chokepoint
  compartido de pago (cubre path agéntico + legacy); handler Habeas Data fail-safe (retry +
  log CRITICAL + aviso pausa manual).
- Encontró **moderados** → cerrados: guard `int('')`, regex de aviso ampliado, tracking en
  prompt EXPLORING.
- **Refutó 2 sobre-afirmaciones mías** (honestidad): "2 UAT marginales" eran **16**; el prompt
  EXPLORING no guiaba el tracking afirmado.

### 3. Pruebas LIVE (bot real, código final `6f2455fe`)
| Palanca | Evidencia live | Estado |
|---|---|---|
| Variante (no miente sobre stock) | "15ml $52.000, 30ml $85.000" (ambas, sin "solo 30ml") | ✅ |
| Habeas Data no-keyword (Ley 1581) | Acuse determinístico exacto + escalación | ✅ |
| Off-topic / dominio comercial | Redirigió, no respondió chiste/mundial | ✅ |
| Recotización intra-turno (add a mitad de checkout) | "Como agregaste un producto, el envío se recalcula. A Medellín, opciones actualizadas: …" — recotiza con ciudad conocida, sin deflección | ✅ |
| Gate pre-pago | 0 órdenes/links generados con envío inválido | ✅ |

> El bug reportado por el founder (conversación sin sentido en add-mid-checkout) fue
> diagnosticado con la observabilidad construida (`[AGENTIC_TRACE]`) — causa: falso positivo de
> `CartRenderCoherenceInvariant` Case A — y cerrado + verificado en vivo.

## Certificado (con evidencia)
- 7 palancas de coherencia (4 construidas + 1 ya-existía + tracking + off-topic) + harness +
  observabilidad + los fixes de los 2 bloqueantes del audit.
- Cada fix es **determinístico** (resolver / invariant / gate, no "el prompt lo guía") y deja
  su **escenario de regresión** o test unitario.

## NO certificado / deuda abierta (honesto)
- **16 escenarios UAT** (S10-S25) no ejecutados en esta tanda.
- **Residual menor:** en el turno del ADD el bot aún pregunta "¿a qué ciudad?" una vez (tiene la
  ciudad; se recupera al turno siguiente usando la conocida).
- **Robustez de borde:** `result.ok` en stock_reservation (depende de excepción por substring);
  regex de ventana fija en no_internals_exposure con falsos negativos.
- **Modelo de datos:** teleporte geo inicial requiere campo `city` estructurado en `contacts`.

## Mapa vivo
Inventario completo estado×intención + estado de cierre: `docs/operations/conversation-coverage-map.md`.
Estrategia + harness + observabilidad: `docs/operations/conversation-coherence.md`.

---
**Firma:** certificación honesta — los flujos core están sólidos, testeados y verificados en
vivo; la deuda restante está enumerada y acotada, no oculta.
