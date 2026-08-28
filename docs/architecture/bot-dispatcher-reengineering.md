# B-2 — Re-ingeniería del dispatcher del bot (formulación arquitectónica)

> **Estado: ✅ VALIDADO por founder 2026-08-28 — 6/6 hacia la opción recomendada, bajo la premisa
> founder vigente: "efectividad y calidad de implementación sin importar tiempo ni esfuerzo" — la
> premisa resuelve las 6 hacia la opción arquitectónicamente correcta (resolución por decisión en §4).
> FASE 0 ✅ EJECUTADA 2026-08-28** (commits `fc4f72e6`/`56a52bc8` — TurnContext v0 + StateResolver al
> inicio + V2 lazy + transitions cableada + 10 constantes muertas fuera) **+ H11 ✅ CERRADO**
> (commit `6f41b992` — primer fix comportamental, founder live PRD; incluye D4 ejecutada).
> **SIGUE: Fase 1** (gates legales sobre ctx + normalizadores + Finalizer v1).
> Origen: directiva founder 2026-08-23 ("validar si existen inclusiones parches… formular de forma
> arquitectónica") sobre la auditoría profunda del bot (`.audit/findings/2026-08-21-bot-deep-audit.md`)
> + los dos inventarios ejecutados 2026-08-28 (`.audit/findings/2026-08-28-bot-patch-inventory-outbound.md`
> = **INV-A**, `.audit/findings/2026-08-28-bot-resolvers-radiography.md` = **INV-B**; ambos con evidencia
> `archivo:línea` verificada contra `develop`).
> Reglas vigentes: STG-first · harness B-3 certifica cada noche que el bot ACTUAL sigue verde (la red
> que hace seguro este strangler) · FIX ARQUITECTÓNICO, no parche · cero suposiciones · cada fase deja
> el turno funcionando igual (migración strangler: comportamiento preservado salvo donde una decisión
> de §4 diga lo contrario).

---

## 1. Qué problema resuelve (síntesis de los inventarios)

**INV-A (outbound fuera del embudo):** el caso canónico del saludo (2026-08-23) no era un incidente
aislado — es el patrón. Hoy:

- **70% de las unidades de política transversal (23/33) viven FUERA del embudo** `OutputValidator`;
  en invariants de texto puros: 17 en el pipeline del dispatcher vs 5 en el validator (77% fuera).
- **5 canales saltan el embudo por completo** (INV-A §1): re-opt-in (el cliente ve `¡`/`¿` que el
  resto de la conversación no tiene), opt-out, detector de silencio, caption de imagen, y la cola
  pgmq cuando el productor no es un retry (notificaciones de refund/envío).
- El pipeline de 17 invariants del dispatcher (dinero, PII, cortesía, formato) **solo cubre el path
  LLM** — los ~15 bypasses pre-LLM no lo corren — y es **first-rewrite-wins** (no compone en cadena;
  caso verificado: el 🙌 de `_GOODBYE_CLEAN` sobrevive a `no_emoji`).
- **3 renderers de resumen de pedido** con formatos de dinero divergentes + **2 templates distintos
  de consent Habeas Data** para la misma acción legal.
- La invocación manual por-callsite de `payment_coherence` en el bypass de shipping
  (`dispatcher.py:2656`) es el mismo anti-patrón que se retiró en el caso canónico.
- 10 constantes de política **muertas** en `orchestrator.py:1140-1640` parecen política viva
  (trampa para futuros edits: el prompt activo vive en `agentic/prompt/`).

**INV-B (resolvers pre-LLM / radiografía para B-2):**

- `_run_agentic_full` creció a ~2.660 LOC (`dispatcher.py:718→3378`); **34 bloques ordenados por
  turno** tabulados: 7 gates + 12 resolvers determinísticos pre-LLM (8 mutan cart/DB ANTES del LLM)
  + resolver FSM + prompt por estado + LLM + post-procesos.
- **Lecturas DB duplicadas por turno (verificado):** `conversations` ×7, `messages` ×5-6 (history
  ×3 + embudo), `contacts` ×2, lookup de cart copiado inline ×9, `coupons` y catálogo (3 q) sin
  cache cada turno — ~20-24 queries secuenciales con caches tibios (35-45 alcanzables en checkout).
- **Fricción FSM vigente:** el estado se resuelve DESPUÉS de las mutaciones (`dispatcher.py:2736`),
  la matriz formal `transitions.py` tiene **0 callers** fuera del paquete, y
  `_resolve_and_persist_agentic_state` se re-invoca 15 veces post-hoc por turno. Gating por agente
  inconsistente (4 resolvers gated, 7 no).
- **15 parches catalogados (P1-P15)**, desde "fix UAT live BUG N" hasta regex-on-outbound en 3
  capas y la doble evaluación del intent COD pre/post LLM.

## 2. La arquitectura destino

```
inbound (worker) ──► Normalizadores (multimodal, no-texto, filtro dominio)
        │
        ▼
   TurnContext  ←── UNA lectura de conv/contact/history/cart al inicio del turno
   (ctx.cart refrescable tras mutaciones; conv×7→1, messages×5→1, contacts×2→1)
        │
        ▼
   Legal gates (etapa única sobre ctx — los 0a-0f de hoy, compliance intacta)
        │
        ▼
   StateResolver (estado FSM al INICIO del turno — hoy se resuelve DESPUÉS de mutar)
        │
        ▼
   State handler del estado (PAYMENT / CART_BUILDING / SHIPPING_QUOTE /
   CARRIER_SELECTION / PII_COLLECTION / POST_PAYMENT / …) — uno por estado,
   sobre los contratos de dominio estables (Track 5 M2: orders/claims/payments
   ya viven en konvi_domain; el resto migra en su fase)
        │
        ▼
   LLM (per-state prompt) SOLO si el handler no resolvió — con tools validadas
        │
        ▼
   TurnFinalizer ÚNICO — trace, audit, summary-regen, race-gate, escalaciones,
   degraded path; persistencia del estado UNA vez
        │
        ▼
   EMBUDO ÚNICO de salida (OutputValidator extendido) — TODA política transversal:
   formato WhatsApp (hoy lib/response_format), cortesía, PII, verdad de dinero
   (invariants re-expresados sobre ctx, no regex de texto), captions e incluso la
   cola pgmq (contrato: solo texto post-embudo entra a la cola)
        │
        ▼
   Meta
```

Tres reglas permanentes que esto formaliza:

1. **La política transversal vive en el embudo** (regla del caso canónico, hoy violada al 70%).
2. **El estado se resuelve antes de mutar** (INV-B P10) y se persiste una vez en el finalizer.
3. **Cada capacidad de negocio vive una vez** — en el domain service (Track 5); el handler la
   consume. Los espejos congelados se adoptan defendidos por los tests de paridad existentes.

## 3. Plan de extracción por fases (strangler — riesgo bajo → alto)

Cada fase deja el turno funcionando igual y se certifica con el harness (§5).

**Fase 0 — gratis (sin cambio de comportamiento):** ✅ **EJECUTADA 2026-08-28** (commits
`fc4f72e6` + `56a52bc8`; 12 tests nuevos en `tests/agentic/test_turn_context.py`): V2 lazy ·
StateResolver al inicio del turno (post agent-router, pre-resolvers de dinero; `turn_ctx=`
al resolver) · `transitions.py` CABLEADA como telemetría log-only (UNEXPECTED→WARNING) ·
**TurnContext v0** (`agentic/turn_context.py`: una lectura por entidad; cart refrescable con
`update_cart_fields` coherente; derivados del history) · las 10 constantes muertas de
`orchestrator.py` retiradas (con sus tests muertos). Nuances documentadas en los comentarios
del código: prompt per-state ve el estado de ENTRADA (turnos consent/carrier que siguen al
LLM) · badge en el path LLM refleja el estado de entrada hasta el próximo turno (los bypass
terminales lo refrescan post-mutación como hoy) · los lookups con filtro divergente
(`status='open'` del shipping/abandoned, `get_cart_with_items` del recipient) NO migraron —
son scope de sus handlers (Fase 2-3).

**Fase 0+ — H11 (primer fix comportamental, founder live PRD 2026-08-28):** ✅ CERRADO
(commit `6f41b992`, 18 tests nuevos en `tests/agentic/test_h11_claim_flow.py`): el reclamo
sin pedido identificable ya NO deriva al consent de compra ni en loop. Diseño: la VOZ la
lleva el LLM (reglas de reclamo en `greeting`/`exploring`/`post_payment` prompts) y lo
determinístico es la ACCIÓN (FakeEscalation cubre enclíticos + markdown; la promesa de
especialista siempre fuerza takeover real) + consent con framing de reclamo en el embudo
(`CONSENT_QUESTION_TEMPLATE_CLAIM` vía `is_claim_context` — D3 matizada: UN template por
CONTEXTO, ambos desde el embudo) + D4 EJECUTADA (🙌 fuera de `_GOODBYE_CLEAN` y del
auto-exit del worker). xfail `t8_reclamo_coherente` retirado (pasa).

**Fase 1 — gates y normalizadores (bajo):** gates legales → etapa sobre ctx · normalizadores
de inbound · filtro de dominio terminal · image-request tras regex barata (hoy lee messages en
TODO turno) · **Finalizer v1** (trace+audit+summary+race-gate+escalaciones+degraded unificados).

**Fase 2 — embudo consolidado + handlers sin dinero (medio):** la corriente de INV-A —
**el OutputValidator absorbe la batería de formato + la política de cortesía/PII/dinero
re-expresada sobre ctx**; los 5 canales bypass se rutean por el embudo; los 17 invariants del
dispatcher se migran/retiran a medida que su política aterriza en el embudo (composición en
cadena, no first-rewrite-wins) · handlers PII_COLLECTION (consent) + recipient intent ·
routing de tools/guardrails unificado (cierra el gating inconsistente) · detección COD/online
unificada en ctx (precondición de la Fase 3).

**Fase 3 — handlers acoplados al dinero (alto, uno por vez, con regresión UAT):** COD intent →
PAYMENT · carrier select · shipping quote (incl. el invariant suelto al finalizer) ·
purchase/variant continuation → CART_BUILDING (renderer canónico único — cierra los 3 renderers
divergentes) · cupón (totales + invalidación de orden pending_payment) · **cancel/retracto B6 de
ÚLTIMO** (void de dinero real, confirmación en 2 turnos, audit SIC — mayor blast radius
legal-financiero) · payment availability se disuelve en PAYMENT tras decidir P12 (§4.1).

## 4. Decisiones — ✅ VALIDADAS por founder 2026-08-28 (6/6 hacia la recomendada)

**Premisa founder vigente (2026-08-28):** "efectividad sin importar la estrategia — primar la
calidad de implementación, sin importar el tiempo de esfuerzo". Bajo esa premisa las 6 se
resuelven hacia la opción arquitectónicamente correcta; no quedaron dudas abiertas que preguntar.
Resolución y razón por decisión:

1. **Divergencia doc↔código (INV-B P12) → (a) respuesta directa determinística** cuando el modo de
   pago es unívoco. Razón: menos LLM = menos superficie de alucinación de dinero (regla "No Magia
   LLM": el LLM nunca es fuente de verdad de capacidades/estados). `payment_method_availability_resolver`
   se disuelve en el handler PAYMENT (Fase 3) con respuesta determinística.
2. **Los 17 invariants del dispatcher → (a) migrar la política al embudo** y re-expresar los de
   dinero sobre ctx (no regex de texto) a medida que su handler migra (Fase 2). La opción (b) era el
   parche barato que dejaba la fragmentación de INV-A viva.
3. **Consent Habeas Data duplicado → (a) template único = `CONSENT_QUESTION_TEMPLATE`**
   (`orchestrator.py:45-56`, rev. 89.b+91). Razón: es el texto legalmente más completo (consent
   previo + expreso + informado + REVOCABLE — menciona el borrado) y ya es el aprobado en producción
   que ve la mayoría de paths; unificar sobre él no introduce texto legal nuevo, mata el duplicado
   (el rewrite de `consent_required.py:82-89` pasa a consumirlo).
   *Matiz ejecutado 2026-08-28 (H11, commit `6f41b992`):* UN template por CONTEXTO — en contexto de
   reclamo el embudo usa `CONSENT_QUESTION_TEMPLATE_CLAIM` (misma acción legal, framing on-topic);
   el de compra sigue único para el contexto de compra. La migración del rewrite del invariant
   (`consent_required.py`) queda para Fase 2 (con el embudo consolidado).
4. **Política de emojis → (a) quitar 🙌** — ✅ EJECUTADA 2026-08-28 (commit `6f41b992`): fuera de
   `_GOODBYE_CLEAN` (`post_escalation_coherence.py:43-47`) y del auto-exit (`worker.py:1963`).
   Razón: el 🙌 sobrevive por el bug first-rewrite-wins, no por decisión de marca; la whitelist del
   DS ya está definida (📋🚚✅💵). Consistencia = calidad.
5. **Captions de imagen y la cola pgmq → (a) extender el embudo** a captions + contrato "solo texto
   post-embudo entra a la cola" (las notificaciones de refund/envío pasan por el embudo al encolar,
   Fase 2).
6. **Renderers de dinero → (a) unificar los 3 resúmenes sobre `cart_render.py`** (canónico ADR-0026)
   — formato de dinero único en todas las superficies (Fase 3, CART_BUILDING).

## 5. Instrumento de aceptación (por qué esta migración NO va a ciegas)

- **Harness B-3 (la red):** corre en CI nocturno (verde hoy: 22/0/7 xfail) y turno a turno en STG
  para los escenarios de dinero — cada fase debe dejarlo verde. Los **xfails H1-H8** (deuda
  conversacional conocida) se retiran a medida que el comportamiento se corrige — el runner obliga
  (XPASS = falla hasta retirar el marker).
- **Tests de paridad** por fase (el patrón ya probado en M2: outcome bot↔paquete idéntico en DB).
- **Sondas live STG** con navegador real para lo que el operador VE en el inbox.
- **Telemetría acumulada** en `agentic_shadow_log` (Track 6) para la decisión canary de los flags
  (`AGENTIC_STATE_ROUTING_ENABLED` / `AGENTIC_TOOL_VALIDATED_ENABLED` se vuelven default solo con
  evidencia — B-4).
- **Kill switch por fase:** cada fase aterriza detrás del dispatcher existente (strangler); si el
  harness rompe, la fase se revierte sola.

---

*§4 validado por founder 2026-08-28 (6/6 recomendadas, premisa calidad/efectividad sin importar
esfuerzo) — Fase 0 autorizada y en ejecución.*
