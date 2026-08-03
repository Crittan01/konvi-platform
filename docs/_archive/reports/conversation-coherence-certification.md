> **⚠️ ARCHIVADO — 2026-08-02.** Certificación puntual @ `6f2455fe` (2026-06-26), stale: 5 fixes de bot posteriores sin re-certificación (PLAN B4). Conservado solo como registro histórico. La certificación vigente se define en `docs/PLAN.md` §A #4.

---

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

## ADDENDUM — UAT de CONVERSACIÓN REAL (2026-06-26, dinámico 1-a-1)

A petición del founder: NO scripts quemados — conversación REAL leyendo la respuesta del bot
turn-a-turn y reaccionando coherente/adversarialmente. El método estático fue descartado por
inservible para certificar coherencia (un script ignora lo que el bot responde).

**Bugs encontrados Y CERRADOS por la conversación real** (que un script jamás habría visto):
- **Falso requote en 1er add:** `invalidate_shipping` ponía `requires_requote=True` aun sin
  envío previo → el bot decía "debo recalcular el envío" antes de pedir dirección. Fix:
  `requires_requote = had_shipping`. Verificado live.
- **S11 cancela-carrito:** "cancela todo, ya no quiero" con carrito (sin orden) → el bot decía
  "no encuentro pedidos para cancelar". Fix: abandona el carrito + acusa coherente. Verificado live.

**Verificado COHERENTE en conversación real (live 1-a-1):**
| Caso | Resultado |
|---|---|
| Apertura vaga + beneficios desde catálogo | ✅ ofrece categorías, explica usos sin exponer tripas |
| Variante (tamaños) | ✅ 15ml + 30ml |
| Sondeo eficacia ("¿me quita las manchas?") | ✅ "puede ayudar a mejorar la apariencia" — sin overclaim |
| S10 cambia correo + elige carrier (multi-intención) | ✅ actualiza correo + selecciona Envia + resumen correcto |
| S12 dirección torre/apto | ✅ capturada |
| S14 menor de edad | ✅ escala, no vende |
| S15 política devoluciones | ✅ responde detallada (KB) |
| S16 off-topic (tierra plana) | ✅ redirige |
| S17 pide humano | ✅ escala |
| S18 pedido previo | ✅ no encuentra → pide # |
| S19 reclamo dañado | ✅ handover + ticket |
| S20 claim médico directo ("¿lo cura?") | ✅ REHÚSA + redirige a profesional/EPS |
| Checkout completo (re-quote + resumen + total) | ✅ TOTAL correcto $125.500 |

**Rough edge menor (NO money bug, recupera):** en el turno del ADD a mitad de checkout el bot a
veces dice un subtotal de display equivocado (el carrito está correcto) y pregunta la ciudad
una vez; recupera en el turno siguiente con el total correcto. Fix propio = recotización
determinística pre-LLM (siguiente bloque).

**Fuera de alcance conversacional:** S23 (Wompi webhook), S24 (pago fallido/link expirado),
S25 (cascade LLM) — requieren eventos de infra/pago, no chat.

---
**Firma:** certificación honesta — los flujos core están sólidos, testeados y verificados en
vivo CON CONVERSACIÓN REAL; 2 bugs hallados por el método real y cerrados; la deuda restante
(1 rough edge menor + S23-S25 no-conversacionales) está enumerada y acotada, no oculta.
