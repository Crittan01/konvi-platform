# Estrategia Definitiva — Elevación Durable de Scores de Dominio del Inbox

> Documento de arquitectura. Consolida diseño (fitness functions + rúbrica + roadmap) **ya ajustado** por las dos críticas adversariales. Cada afirmación load-bearing fue re-verificada contra HEAD (`feat/A6-A7-quality-first-rev111`), no contra la foto del audit. Extiende infraestructura probada (`scripts/audit_tenant_filter.py`, `tests/test_coherence_pact.py`, `scripts/validate.sh`); no inventa frameworks.

---

## 1. Tesis

**Atacamos clases de falla + enforcement de su forma, NO el número.** El "70/100" de la auditoría es opinión comprimida; cablearlo a CI sería Goodhart puro. Lo que se cablea es la **imposibilidad de re-mergear la forma del bug** mediante lints/pacts binarios (ADR-0024) con test de auto-validación (fixture-bug → el check detecta). Un fix de clase cierra N findings; su fitness function impide que la clase reaparezca. El score sube como *consecuencia*, no como objetivo.

**Qué se descartó por las críticas (re-verificado en árbol):**

| Descartado | Evidencia en repo | Razón |
|---|---|---|
| FF-A presentado como bug **activo** de catálogo | `tool_id_referential_integrity.py:77` YA tiene `item.get("variants")` | Anchor remediado. Sobrevive solo como **regresión** (pact estático), no como fix. |
| FF-E sobre `OutputValidator` | `orchestrator.py:1975,2117` lo invocan | Anchor FALSO. Registrarlo daría falso positivo que bloquea refactors correctos. **Eliminado del registro.** |
| FF-A-RPC como "linter genérico de OUT params" | Solo **2 de 17** `RETURNS TABLE` usan prefijo `out_` (12%) | La convención es la excepción. Linter genérico = no-op disfrazado sobre el 88%. **Degradado a test puntual de ~3 RPCs.** |
| Construir **7** fitness functions + `_ast_lint_base.py` compartido | `audit_tenant_filter.py` = 524 líneas monolíticas, `BASELINE_MAX=0` protege la propiedad más crítica | DRY prematuro + refactor del único guardrail que funciona = regresión. **Se construyen ≤3 ratchets.** |
| C-75.3 "`grep X-Internal-Service-Secret tests/` = 0" | Son **3** (`test_a11_dual_auth_integration.py`) | Criterio stale. La rúbrica se re-deriva contra HEAD. |
| "Cada FF extiende infra probada, no inventa" | `test_coherence_pact.py` es **puramente estático** (`model_fields ⊆ fixture JSON`), nunca llama productores | Mentira por omisión: FF-A/B/F **sí** inventan infra. Re-presupuestado. |
| La rúbrica como **gate de CI** | — | Reintroduce el número objetivo. **Degradada a documento de comunicación.** |

**Premisa central de durabilidad (punto ciego no resuelto por el diseño original):** con **1 solo CODEOWNER** (`@Crittan01`, verificado), cada ratchet es una superficie donde, bajo presión de entrega, la salida de menor resistencia es subir el `MAX` o añadir `# exempt`. **Menos guardrails binarios de bajísimo FP son más durables que 7 ceremoniales.** Esto reorienta todo el diseño hacia el recorte.

---

## 2. Rúbrica de madurez (niveles medibles)

Gates acumulativos. Cada criterio es binario con fuente de evidencia. **No es gate de CI**: es mapa de deuda. A CI solo van los lints/pacts del §3.

| Nivel | Significado | Criterios (todos, acumulativos) | Evidencia |
|---|---|---|---|
| **60** | Happy-path, frágil bajo trigger | Sin `critical` abierto de trigger≈1; 0 gaps tenant-filter NEW; toda mutación financiera con idempotencia *alguna* | `audit_tenant_filter.py` (ya en CI, `BASELINE_MAX=0`); grep Idempotency-Key + UNIQUE |
| **75** | Correcto y seguro bajo trigger común | 0 Clase A abierta (pact productor↔consumidor); ningún `except` ancho degrada a camino menos seguro en rutas `MUST_FAIL_CLOSED`; dual-auth S2S cubierto por ≥1 test (**hoy = 3, ya cumplido**); ningún gate compliance corre solo en path muerto | pact catálogo/enum; `audit_broad_except.py` acotado; `test_a11_dual_auth_integration.py`; test paridad legacy↔agentic |
| **90** | La clase de bug es *imposible*, no solo ausente | Entidad cross-boundary = **un único símbolo compartido**; toda mutación del dominio por RPC `FOR UPDATE`+version o CAS; Idempotency-Key determinística (nunca `uuid4()`); health refleja liveness real (503) | constante única importada por ambos lados; lint atomicidad/idempotencia; test que mata worker → 503 |
| **95** | Regresión imposible de mergear (techo realista) | Guardrail en `validate.sh --ci` que **falla** si la clase reaparece (con su `test_audit_*` fixture-bug corriendo en suite, NO mutation manual); ≥1 test de race real contra Postgres efímero donde aplique oversell/doble-envío; re-auditoría adversarial firmada | el `test_audit_<clase>.py` verde en CI; test concurrencia; firma humana |

**Composición del score por dominio (anti-promedio-plano):** `score = min ponderado de las dimensiones con finding ≥ high`, capeado: **`critical` abierto ⇒ ≤68**; `high` de `security_multitenant`/`compliance` ⇒ `≤75`. Cerrar lows NO compensa un crítico. **95 es el techo** (100 exigiría observabilidad multi-réplica + chaos, fuera de scope = Goodhart). El "mutation test" pasa de manual (lo saltará un equipo de 1 bajo presión) a **`test_audit_*` en la suite siempre** — esa es la única anti-no-op durable.

---

## 3. Fitness functions por clase (capa de durabilidad) — recortada

**Decisión rectora:** **3 guardrails con ratchet** (las clases más extendidas y verificadas) + **tests puntuales en pytest** para el resto (sin baseline CSV ni CODEOWNERS que mantener). Cada guardrail con ratchet replica el patrón `test_audit_tenant_filter.py` (24 tests, verificado) con fixture-bug. **No se extrae `_ast_lint_base.py` hasta tener ≥3 linters estables**; si se extrae, será por *performance* (un solo `ast.parse` por archivo con N visitors sobre los 217 .py), no por DRY.

### Construir (ratchet + CODEOWNERS):

**G1 — `audit_broad_except.py` (Clase C).** Anchor verificado: 71 en `dispatcher.py`, 50 en `worker.py`, 712 total. **Regla acotada para FP≈0** (corrigiendo la regla 2 original que era juicio semántico prohibido por ADR-0024): detecta SOLO `except` que captura `KeyError|NameError|TypeError|AttributeError` (junto o como `Exception`), NO re-raisea, **y** está en el set `MUST_FAIL_CLOSED` (consent / opt-out / tenant-resolution / sweep). Eso es ~decenas de sitios, cada uno un bug real (el `KeyError: tenant_id` del sweep, el `NameError sys`), no 712. **Se descarta la regla "logger.warning sin métrica = fail-open"** (inauditable sin semántica). Baseline `BROAD_EXCEPT_MAX` decreciente; `MUST_FAIL_CLOSED` con baseline 0 duro.

**G2 — pact de catálogo/enum (Clase A).** Extiende `test_coherence_pact.py` de forma **honesta**: NO llama al productor con DB real (costaría DB efímera por test). Usa el fixture de fila de catálogo en `db_schema_canonical.json` y verifica que productor (`get_tenant_catalog`) y consumidor (invariant) leen la **misma constante** `CATALOG_VARIANTS_KEY` (refactor del literal duplicado). Mismo patrón para `ConversationStatus.HUMAN_TAKEOVER`. Binario pass/fail, sin baseline. Es regresión del fix ya hecho, no fix.

**G3 — `audit_idempotency_key.py` (Clase G).** Anchor verificado: `shipping_quote_tool.py:1345` = `f"inbox-quote-{uuid.uuid4()}"`. Regla binaria limpia: subárbol AST asignado a `"Idempotency-Key"`/`idempotency_key=` que contiene `Call` a `uuid4`/`token_hex`/`urandom` → gap. Conteo objetivo 0-3 → ratchet ligero o test binario directo.

### Tests puntuales en pytest (sin maquinaria de ratchet):

- **FF-E `audit_dead_guarantee`** → test de callgraph mínimo. Registro inicial = **solo `get_transaction_with_resilience`** (0 callers confirmado por el propio comentario "API INTERNA lista para callers"). `OutputValidator` **excluido** (tiene 2 callers). Es el mejor anclado y más barato del set: súbelo de prioridad.
- **FF-D atomicidad** y **FF-F health** → tests puntuales. FF-D es semánticamente débil (`.eq("version")` da FP en inserts legítimos y FN en CAS por `updated_at`/`WHERE stock>=qty`); NO se convierte en ratchet con baseline. FF-F health = test que fuerza `_worker_status['running']=False` y asserta 503 (`api/main.py:155` aún retorna `{"status":"ok"}` literal — gap real, test puntual basta).
- **FF-B dual-auth** → ya cubierto (3 tests existen). Mantener, no construir registro AST.

### Regla anti-no-op:
El exempt-marker exige **finding-id del audit** (`# broad_except:exempt:WMP-3`), no prosa libre → auditable a futuro. Cada `audit_*.py` lleva su `test_audit_*.py` con fixture-bug **corriendo en la suite siempre**.

---

## 4. Roadmap por olas (ataque a clase)

Compuertas: **[CODE-ONLY]** mergeable con `--ci` verde · **[FOUNDER-MIGRATION]** toca prod (ledger con drift, autorización explícita) · **[HOT-PATH]** sesión dedicada + UAT dinámica online turn-a-turn (`feedback_no_static_uat`).

**Corrección a las críticas:** Ola 0 NO está "cerrada"; está **code-complete, UAT-pendiente** (los fixes de catálogo/FSM son hot-path de conversación). La prueba negativa de G2 debe correr contra el bug REAL reproducido, no solo fixture sintética.

| Ola | Clase | Qué (fix + FF) | Target score | Esf | Gate | DoD |
|---|---|---|---|---|---|---|
| **1. Quick-wins durables** | F, G, residuos | WMP-1 reconciliación vía cron (`get_transaction_with_resilience` ya existe sin caller — solo falta cron, NO esperar a Ola 5); `/agentic/metrics` auth+`tenant_id`; ORD-01 ALLOWED_TRANSITIONS; G3 idempotencia determinística + `/health` 503 (`api/main.py:155`) | Payments→78, Obs→80, Orders→70, Shipping→74 | S | [CODE-ONLY] | cron reconcilia ≥1 orden en log local; metrics 401 sin secret; `patch_order` 409 en `delivered→pending`; `--ci` verde |
| **2. FITNESS anti-clase** | A, C, G (prevención) | **G1 broad-except acotado + G2 pact-catálogo + G3 idempotencia**, como scripts **independientes** (sin base común). FF-E test puntual. **Congelar baselines C/G en estado ROTO ahora** (ratchet activo desde día 1, cierra hueco temporal) | No sube; **congela** | M | [CODE-ONLY] | cada `test_audit_*` verde; **prueba negativa contra bug real** hace fallar `--ci`; exempt-marker exige finding-id |
| **3. Seguridad multi-tenant** | IDOR | RPCs `consume/release/extend` con `p_tenant_id` (hoy solo `p_reservation_id` = IDOR real verificado); WH-01 tenant HMAC autoridad + `UNIQUE(meta_waba_id)`; RLS GUC a ADR | Inventory→82, Webhooks→82, MT→88 | M | **[FOUNDER-MIGRATION]** | **expand-contract**: sobrecarga `consume(p_reservation_id,p_tenant_id)` coexiste, migrar callers, dropear vieja en migración posterior. NUNCA cambiar firma in-place |
| **4. Compliance agentic** | E (código muerto compliance) | Portar gates HARD `summary-before-link`+`no-pii-pre-consent` a `apply_invariants` + test paridad; HD audit canónico en POST/PATCH | Anti-hallu→82, Habeas→88, Prompt→80 | M | [CODE-ONLY] | path agentic LIVE ejecuta ambos gates; paridad legacy↔agentic verde |
| **5. Integridad transaccional** | D | `rpc_create_order_with_items` + `uniq_active_order_per_conv`; RPCs cart atómicos; decremento stock atómico (oversell) | Orders→85, Cart→86, Inventory→90 | L | **[FOUNDER-MIGRATION]**+**[HOT-PATH]** | crear orden = 1 transacción o rollback; **oversell imposible bajo test de race Postgres efímero** (infra nueva, presupuestada); trace E2E sin regresión |
| **6. Durabilidad ingestión** | F | Cola durable pre-200; dedup `webhook_event_check_or_register` 1er paso; DLQ pgmq | Webhooks→88, Worker→85, Orch→85 | L | **[FOUNDER-MIGRATION]**+**[HOT-PATH]** | mensaje persistido ANTES del 200; reentrega no reabre conversación cerrada; poison→DLQ |
| **7. Observabilidad que acciona** | C, F | Estrechar `except` (G1 sube cobertura); logging JSON + correlation_id; circuit breaker Wompi/WhatsApp/Aveonline; tokens/costo por turn | Obs→85, Orch→88, transversal | M | **[HOT-PATH]** | ningún `except` traga KeyError/NameError en hot-path; cada degradación emite métrica; `total_tokens>0` |

**Por qué Ola 2 antes que 3-7:** las olas estructurales tocan los contratos donde nació la Clase A; sin la FF en CI primero, un refactor puede divergir productor↔consumidor y pasar verde. **Por qué Ola 3 antes que 5:** los RPC transaccionales de Ola 5 deben nacer ya `p_tenant_id`-scoped (fixear IDOR después = refactor doble). Ola 1 y 4 paralelizables ([CODE-ONLY], no comparten archivos).

**Gap no cubierto por las 7 FF (crítica H11):** los fixes de Ola 0 (Wompi monto/moneda, sweep `tenant_id`) NO tienen test de regresión nominal. **Añadir un test por cada fix de Ola 0** dentro de Ola 2 — revertir `98230224` no rompe ningún CI hoy.

---

## 5. Objetivo realista y governance

**Promedio destino ≈ 85** (no 87.5; ningún dominio a 95 sin re-auditoría adversarial firmada). Por dominio el target del §4 es **mapa de deuda interno, NO contrato de CI** — computar el promedio es señal Goodhart y se reporta solo como contexto, nunca como gate.

**Cómo se mantiene la mejora (durabilidad real, equipo de 1):**

1. **≤3 ratchets, no 7.** Menos superficies de auto-bypass. D/E/F/B = tests puntuales sin baseline que vigilar.
2. **`test_audit_*` con fixture-bug corre SIEMPRE en la suite** (patrón `test_audit_tenant_filter.py`, 24 tests verificado) → el guardrail no se degrada a no-op silencioso. Esto es la parte más durable del diseño; replicarla religiosamente.
3. **Exempt-marker con finding-id obligatorio** → auditable por qué se eximió, incluso por el único CODEOWNER revisándose a sí mismo.
4. **Migraciones restrictivas = 1:1 con su deploy, expand-contract, NUNCA en lote.** Un lote grande contra prod-con-drift maximiza la ventana de inconsistencia migración↔código (IDOR `p_tenant_id` in-place = ventas caídas). DoD de Ola 3/5/6 incluye: "aplicada expand→migrate-callers→contract; verificado que callers viejos no rompen durante la ventana".
5. **Re-auditoría adversarial** firma el salto 90→95 por dominio (Tier 3, no automatizable). Las migraciones a prod compartida exigen autorización founder explícita.
6. **Protocolo re-scoring falsable:** afirmar "subí Orders 62→85" exige exhibir el RPC mergeado + test transaccional + `uniq_active_order_per_conv` en migración + el guardrail que falla si se revierte. Sin evidencia, la afirmación es falsa por definición.

---

## 6. Qué NO hacer (anti-patrones de esta iniciativa)

- **NO construir 7 fitness functions de golpe + `_ast_lint_base.py`.** Es la trampa de scope: se mergea el 40%, el resto se pudre. Construir **2-3 reales** primero (G1+G2, luego G3).
- **NO extraer base compartida desde 1 ejemplo.** DRY especulativo. Refactorizar el linter `BASELINE_MAX=0` que ya protege la propiedad más crítica = regresión por estética. Copiar-pegar 200 líneas es feo pero seguro. Extraer solo con ≥3 linters estables y justificado por perf.
- **NO construir FF-A-RPC como "linter genérico de OUT params".** El prefijo `out_` existe en 12% de RPCs; el fallback "exemptar las no parseables" vacía el check para el 88% → protege solo los 2 ya arreglados = la Clase E que dice combatir. Reemplazar por test puntual de los ~3 RPCs indexados por string.
- **NO registrar `OutputValidator` en dead-guarantee.** Tiene 2 callers; sería FP que bloquea refactors correctos.
- **NO cablear el score (ni el promedio) a CI.** Solo lints/pacts binarios. El número es comunicación.
- **NO presupuestar Ola 2 como "M, extensión barata".** FF-A/B/F inventan infra (invocar productores, registro AST de deps, arrancar app de test). Re-presupuestar antes de comprometer.
- **NO declarar Ola 0/cualquier fix hot-path "cerrado" por test verde + commit.** Exige UAT dinámica online turn-a-turn contra DB real (`feedback_no_static_uat`, `feedback_analytical_uat`).
- **NO agrupar migraciones restrictivas en lote** para "ahorrar ventanas de autorización" — optimiza la variable equivocada y maximiza el ordering hazard.
- **NO usar mutation test manual al certificar** como anti-no-op. Un equipo de 1 bajo presión lo salta. El `test_audit_*` en suite es la única garantía.

---

**INTERVENCIÓN HUMANA REQUERIDA.** RESPONSABLE: founder (@Crittan01). PASOS: (1) aprobar G1+G2+G3 + sus baselines en `.github/CODEOWNERS`; (2) confirmar `BROAD_EXCEPT_MAX`/`IDEMPOTENCY_MAX` iniciales tras computarlos (no calculados aún — primer paso de implementación, no dato cerrado); (3) autorizar migraciones de Olas 3/5/6 en expand-contract, una por deploy. CRITERIO DE ÉXITO: `validate.sh --ci` ejecuta los ≤3 guardrails, cada uno con su `test_audit_*` verde; ningún baseline regenerable sin review; ninguna migración restrictiva aplicada in-place. RIESGO si se omite el recorte: 40 piezas de meta-infraestructura con FP → founder regenera baselines para desbloquear PRs → los guardrails colapsan a no-ops simultáneos, dando la falsa señal "CI me protege" — peor que no tenerlos.