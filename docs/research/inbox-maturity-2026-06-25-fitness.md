I have everything needed. The resolver literal lives elsewhere (the audit cited `resolver.py:72` but the grep shows the agentic FSM is structured differently — the key point for the fitness function is the literal-vs-DB-enum mismatch, which my Class A design covers via the RPC/enum coherence pact). I have verified all seven class anchors against the tree. Producing the prevention layer design.

---

# Capa de prevención — 7 fitness functions contra reintroducción de clases sistémicas A–G

> Modelo base: `scripts/audit_tenant_filter.py` (lint AST + ratchet `BASELINE_MAX=0` en `validate.sh §4.5`) + `tests/test_coherence_pact.py` (pact DB↔Pydantic contra fixture canónico). Cada FF extiende **uno de estos dos mecanismos ya probados**, no inventa infraestructura nueva. Todos se integran como un bloque numerado en `validate.sh` con su propio `_ok/_err`, y todos protegen su baseline/fixture vía `.github/CODEOWNERS` (igual que `/gaps_tenant_filter_baseline.csv`).

## Principio rector (anti-Goodhart)

El "score 70/100" de la auditoría **no se cablea a CI**. Lo que se cablea es la **imposibilidad de reintroducir el mecanismo de falla**, no la métrica. Cada FF tiene un **test de auto-validación** (como `tests/test_audit_tenant_filter.py`) que prueba contra una fixture-bug que el check SÍ lo detecta — así el guardrail no se degrada a no-op silencioso (la propia Clase E que combatimos). Ratchet decreciente: baseline solo baja; subirlo exige review CODEOWNERS.

Tabla resumen:

| FF | Clase | Mecanismo base que extiende | Tipo | Baseline/Ratchet |
|---|---|---|---|---|
| FF-A | Contrato desincronizado productor↔consumidor | `test_coherence_pact.py` (pact) | pact test contra **output real del productor** | 0 mismatches |
| FF-B | Dual-auth sin red de regresión | `test_coherence_pact.py` (cobertura) | pact test de cobertura S2S | ≥1 test por dep transversal |
| FF-C | `except` ancho fail-open | `audit_tenant_filter.py` (lint AST) | lint AST + ratchet | `MAX_BROAD_EXCEPT` decreciente |
| FF-D | Read-modify-write fuera de RPC | `audit_tenant_filter.py` (lint AST) | lint AST allowlist | 0 mutaciones nuevas no-RPC |
| FF-E | Código muerto que finge garantía | `audit_tenant_filter.py` (lint AST callgraph) | lint AST "no caller" en módulos sellados | 0 sin-caller en registro |
| FF-F | `/health` 200 con worker muerto | smoke en `validate.sh` | smoke + lint AST | 0 health incondicional |
| FF-G | Idempotencia decorativa (uuid4) | `audit_tenant_filter.py` (lint AST) | lint AST | 0 keys aleatorias en idempotency |

---

## FF-A — `audit_data_contract.py` — Pact contra el **output real del productor**

**Qué detecta exactamente.** La causa raíz de Clase A: un consumidor lee una clave/columna que el productor no emite, y el test pasa porque mockea la forma rota. Tres contratos cross-boundary confirmados en la auditoría:

1. **Catálogo**: `tools/catalog_tool.py:116` emite `"variants"`; `agentic/invariants/tool_id_referential_integrity.py:75-76` lee `product_variations`/`variations`. Verificado en árbol.
2. **Retorno de RPC**: las RPC declaran OUT params con prefijo `out_` (`20260502000000_stock_reservations.sql:129` → `out_reservation_id`), pero `payment_link_tool.py:445` lee `reservation_id`.
3. **Enum literal vs DB**: literales de estado de conversación/FSM (`human_handoff`) vs valor canónico DB (`human_takeover`).

**Cómo se implementa (mecanismo, no mock).** Extiende `test_coherence_pact.py` pero invierte la dirección: en vez de fixtures estáticas, **llama a la función productora con un fixture mínimo y captura el set de claves real**, luego verifica que el consumidor lee de ese set.

- Archivo: `tests/test_data_contract_pact.py`.
- **Contrato de catálogo** (binario, sin NLP — cumple ADR-0024): se invoca `get_tenant_catalog` (productor) con un fixture de 1 producto y se extrae `set(item.keys())` del primer item. El test afirma que la clave que el invariant lee (`tool_id_referential_integrity._extract_variation_key()` — se refactoriza el literal a una constante única `CATALOG_VARIANTS_KEY`) ∈ ese set. Si alguien cambia la clave en uno y no en el otro, el pact rompe.
- **Contrato de RPC**: nuevo `scripts/audit_rpc_contract.py` (lint AST + parse SQL) que (a) extrae de `supabase/migrations/*.sql` los nombres de OUT params de cada `RETURNS TABLE(...)` (regex ya probado en `discover_tenant_scoped_tables_from_migrations`), y (b) detecta en `services/**/*.py` todo `.rpc("<name>", ...)` cuyo resultado se indexa con `[ "<key>" ]`/`.get("<key>")` y exige que `<key>` ∈ OUT params de ese RPC. Para `payment_link_tool.py:445` esto falla hoy (`reservation_id` ∉ `{out_reservation_id, out_expires_at, out_available_after}`).
- **Single source of truth**: cada contrato cross-boundary se materializa como **una constante compartida** (`CATALOG_VARIANTS_KEY`, enum `ConversationStatus.HUMAN_TAKEOVER`); el pact prohíbe literales duplicados divergentes.

**Integración a `validate.sh`.** Bloque nuevo `§2c — Data contract pact`: corre `python3.11 scripts/audit_rpc_contract.py --max-mismatch "$RPC_CONTRACT_MAX"`; el pact de catálogo/enum corre dentro de la suite pytest (ya ejecutada en §2). En `--ci` los warns→fails.

**Ratchet/baseline.** `RPC_CONTRACT_MAX=0` (env, decreciente). El pact de catálogo no tiene baseline: es binario pass/fail. Protección CODEOWNERS sobre `scripts/audit_rpc_contract.py` y la constante `CATALOG_VARIANTS_KEY`.

---

## FF-B — `test_dualauth_coverage_pact.py` — Cobertura forzada del path internal-secret

**Qué detecta exactamente.** El punto ciego que dejó pasar Clase B: `grep 'X-Internal-Service-Secret' tests/` → 0. Los 4 paths S2S quedaron remediados (`plans.py:60`, `security.py:142`, `auth.py:241`) pero sin red de regresión. Detecta toda **dep transversal de auth nueva sin test del path internal-secret**.

**Cómo se implementa.** Pact de cobertura (extiende el patrón "fixture canónico → assert subset" de `test_coherence_pact.py`, aplicado a un inventario de deps en vez de columnas):

- Archivo: `tests/test_dualauth_coverage_pact.py`.
- Se mantiene un **registro canónico** `DUAL_AUTH_DEPS` (lista de `(módulo, función)` que aceptan `X-Internal-Service-Secret`), descubierto por AST: toda función en `services/*/dependencies/` y `services/*/routers/` que referencie el header internal-secret o llame a `get_tenant_id_internal_or_user`.
- El pact afirma: (a) cada dep del registro tiene ≥1 test que ejercita la rama internal-secret (detectado por AST: un test que construye headers con el secret e invoca la dep), y (b) **toda dep descubierta por AST está en el registro** (si aparece una dep nueva sin entrada → falla, forzando autor a añadir test).
- Componente AST `scripts/audit_dualauth_coverage.py` produce el set "deps que aceptan internal-secret" vs "deps con test que lo ejercita"; la diferencia es el gap.

**Integración a `validate.sh`.** Corre dentro de pytest (§2). El componente AST corre como `§2d`.

**Ratchet/baseline.** Baseline = 0 deps sin cobertura. Ratchet inverso al de tenant-filter: **el registro solo crece**; ninguna dep puede salir sin review CODEOWNERS. Protección sobre `audit_dualauth_coverage.py`.

---

## FF-C — `audit_broad_except.py` — Lint AST de `except` ancho fail-open

**Qué detecta exactamente.** Clase C: 71 `except Exception` en `dispatcher.py`, 50 en `worker.py`. El check NO prohíbe `except Exception` en general (no accionable) — detecta el **patrón fail-open inseguro específico**: un `except Exception` (o `except` desnudo, o `except (..., Exception)`) cuyo cuerpo **retorna un default que abre el camino menos seguro** sin emitir señal. Reglas AST binarias (ADR-0024):

1. `except` que captura `KeyError`/`NameError`/`TypeError`/`AttributeError` junto con (o como) `Exception` **y los traga** (estos son bugs de programación, no fallos de I/O — exactamente el `KeyError: tenant_id` del sweep `worker.py:953` y el `NameError` de `sys` en `worker.py:1877`). Binario: ¿el handler re-raisea o solo `log+return`?
2. `except Exception:` cuyo cuerpo es `return None`/`return False`/`return ''`/`return []` **sin** una llamada a métrica/Sentry en el handler (detectable por AST: ¿hay un `Call` a `capture_exception`/`metric`/`logger.error` con `exc_info`?). Solo `logger.warning` sin métrica = fail-open silencioso.

**Cómo se implementa.** Clon estructural de `audit_tenant_filter.py`: `FileVisitor(ast.NodeVisitor)` con `visit_ExceptHandler`, mismo sistema de `Gap`/CSV/`--baseline`/`--max-gaps`/`--quiet`/exempt-marker.

- Archivo: `scripts/audit_broad_except.py`.
- Reusa el `_EXEMPT_MARKER` (`# broad_except:exempt:<reason>`) para los casos legítimos de I/O esperado (con razón obligatoria).
- **Fail-closed enforced por allowlist**: rutas de consent/opt-out (`agentic/.../consent`, `_should_skip_for_conv_status`) marcadas `MUST_FAIL_CLOSED` → en esas funciones, un `except` que retorna "no-skip"/"continuar" es gap inmediato (no ratchet, baseline 0 duro).

**Integración a `validate.sh`.** `§4.6 — Broad-except fail-open lint`, idéntico al bloque §4.5: baseline CSV + `--max-gaps "$BROAD_EXCEPT_MAX"`.

**Ratchet/baseline.** `BROAD_EXCEPT_MAX` = conteo actual congelado como baseline (decreciente). Las rutas `MUST_FAIL_CLOSED` con baseline 0 duro desde el inicio. Cada P1 "estrechar except" baja el número.

---

## FF-D — `audit_atomic_mutation.py` — Lint AST de read-modify-write fuera del RPC

**Qué detecta exactamente.** Clase D: mutaciones de cart/stock que hacen `SELECT → compute en Python → UPDATE` evitando el RPC atómico (`cart_add_item`, `rpc_stock_reserve`). Detecta sobre un set `ATOMIC_ONLY_TABLES = {conversation_carts, cart_events, product_variations (col stock), stock_movements, stock_reservations}`: cualquier `.table(X).update(...)`/`.insert(...)` sobre una columna de cantidad/stock/shipping_meta que **no** vaya acompañada de `.eq("version", ...)` (CAS) **ni** sea una `.rpc(...)`. Casos confirmados: `cart_tool.py:663-673` (`set_shipping_meta` sin `WHERE version`), `_decrement_stock_on_confirm` (`new_stock = current - qty` en Python), `order_cancellation.py:620`.

**Cómo se implementa.** Extiende directamente `audit_tenant_filter.py` (mismo árbol de chain-walking `.table().update()`):

- Archivo: `scripts/audit_atomic_mutation.py` (o regla nueva dentro del visitor existente — reusa `_collect_chain_methods`/`_chain_starts_from`).
- Regla: si `table ∈ ATOMIC_ONLY_TABLES` y hay `.update(payload)` donde `payload` toca una clave de un set `MUTABLE_QTY_KEYS = {stock, available_stock, quantity, shipping_meta, ...}` y **no** hay `.eq("version", _)` en la chain → gap `non_atomic_mutation`. Las mutaciones legítimas pasan por `.rpc("cart_*"/"rpc_stock_*")` (no matchean `.table().update`).
- Exempt-marker reusado para migraciones one-shot legítimas.

**Integración a `validate.sh`.** `§4.7 — Atomic mutation lint`, mismo patrón baseline+ratchet.

**Ratchet/baseline.** `ATOMIC_MUTATION_MAX` = baseline actual (las RMW conocidas), decreciente. Cuando se porten todas a RPC/CAS → 0. CODEOWNERS sobre el set `ATOMIC_ONLY_TABLES`.

---

## FF-E — `audit_dead_guarantee.py` — Lint AST "módulo sellado sin caller"

**Qué detecta exactamente.** Clase E: building blocks completos y testeados, **sin un solo caller en producción**, cuyo docstring promete una garantía (reconciliación P0 `get_transaction*`, `OutputValidator` en agentic, `transitions.py`, `consume_by_cart`/`extend_by_cart`). Detecta funciones registradas como **garantía obligatoria** que no tienen caller en código de runtime (excluyendo tests).

**Cómo se implementa.** Lint AST de callgraph estático (extiende el traversal de `audit_tenant_filter.py` a búsqueda de `ast.Call` por nombre cruzando archivos):

- Archivo: `scripts/audit_dead_guarantee.py`.
- **Registro explícito** `GUARANTEED_CALLERS` (constante en el script, protegida CODEOWNERS): lista de funciones que la auditoría declaró "deben estar cableadas" — `get_transaction_with_resilience`, `OutputValidator.validate` (en path agentic), `consume_by_cart`, etc. Para cada una, el lint construye el set de nombres invocados en todo `services/**/*.py` (excl. `tests/`, excl. el propio módulo de definición) y exige ≥1 caller. 0 callers → gap `unwired_guarantee`.
- Es la **inversión del "código nuevo sin caller no se mergea"** del anti-pattern #4 de la auditoría, hecho enforce: una garantía registrada que pierde su último caller rompe CI.
- Distinción binaria limpia (ADR-0024): "¿existe un `ast.Call` con `func.attr/func.id == nombre` fuera de tests y fuera del módulo de definición?". Sin heurística semántica.

**Integración a `validate.sh`.** `§4.8 — Dead-guarantee lint`. Baseline 0 (toda garantía del registro debe tener caller).

**Ratchet/baseline.** Baseline 0 sobre el registro. El registro crece cuando se cablea código muerto de compliance/reconciliación y se quiere blindar que no se descablee. Quitar una entrada = review CODEOWNERS.

---

## FF-F — `health_smoke.sh` + lint AST de `/health` incondicional

**Qué detecta exactamente.** Clase F: `/health` que retorna 200/`"ok"` incondicional con worker muerto. `api/main.py:155` aún retorna `{"status": "ok"}` literal incondicional; `server.py:54-73` ya fue corregido esta sesión (retorna `degraded`). Detecta cualquier handler de `/health`/`/healthz` que retorne status fijo sin consultar el estado del worker/dependencia.

**Cómo se implementa (dos capas).**

1. **Lint AST estático** `scripts/audit_health_unconditional.py`: localiza funciones decoradas con ruta `/health*` (AST: decorador `@app.get("/health...")`) y flaguea si el cuerpo retorna un dict literal con `"status"` constante **sin** ningún `if`/lectura de estado de worker. Atrapa `api/main.py:155` hoy. Baseline 0.
2. **Smoke runtime** `tests/smoke/test_health_reflects_worker.py`: arranca el app de test, fuerza `_worker_status['running']=False` y afirma que `/health` → 503 (no 200). Es un smoke, no un mock — verifica el contrato observado, alineado con la regla "observabilidad que acciona".

**Integración a `validate.sh`.** El lint AST como `§4.9` (baseline 0). El smoke corre dentro de pytest (`tests/smoke/`). En `--ci` ambos bloquean.

**Ratchet/baseline.** Baseline 0 health incondicional. Extensible al mismo patrón para `/ready` y `/agentic/metrics` (auth obligatoria) cuando se cierren esos P2.

---

## FF-G — `audit_idempotency_key.py` — Lint AST contra `uuid4()` en idempotency

**Qué detecta exactamente.** Clase G: `Idempotency-Key: inbox-quote-{uuid4()}` (`shipping_quote_tool.py:1345`) — key aleatoria que nunca colisiona = idempotencia falsa; y `create_order` del bot que no envía key. Detecta: (a) cualquier valor de un header/campo `Idempotency-Key`/`idempotency_key` cuya expresión contenga `uuid.uuid4()`/`uuid4()`/`os.urandom`/`secrets.token_*` (binario, AST), y (b) llamadas S2S de creación (`_build_internal_headers`/POST a `/orders`) **sin** clave `Idempotency-Key` en los headers.

**Cómo se implementa.** Lint AST clon de `audit_tenant_filter.py`:

- Archivo: `scripts/audit_idempotency_key.py`.
- Regla (a): `ast.Call`/f-string asignado a una clave `"Idempotency-Key"` o kwarg `idempotency_key=` cuyo subárbol contiene un `Call` a `uuid4`/`uuid.uuid4`/`token_hex`/`urandom` → gap `random_idempotency_key`. La key correcta es determinística por intent (`f"inbox-quote-{conversation_id}-{cart_version}"` etc.).
- Regla (b): allowlist `IDEMPOTENT_ENDPOINTS = {"/orders" (POST), ...}`; un POST a esos sin `Idempotency-Key` en headers → gap.

**Integración a `validate.sh`.** `§4.10 — Idempotency lint`, patrón baseline+ratchet.

**Ratchet/baseline.** `IDEMPOTENCY_MAX` = baseline actual (las keys aleatorias/ausentes conocidas), decreciente a 0.

---

## Plumbing común — extender la infra, no duplicarla

Para no reimplementar 7 veces el chain-walking AST, los FF de tipo lint (C, D, E, F-estático, G) **comparten un único módulo base** `scripts/_ast_lint_base.py` extraído de `audit_tenant_filter.py` (la lógica `Gap`/CSV/`--baseline`/`--max-gaps`/`_EXEMPT_MARKER`/`_collect_chain_methods` ya está toda ahí; hoy vive en un solo archivo). Cada `audit_*.py` aporta solo sus reglas `visit_*`. Esto:

- Mantiene **un solo formato de baseline CSV** y un solo contrato de ratchet → un solo bloque de glue por check en `validate.sh`, idéntico al §4.5 existente.
- Cada baseline + cada `audit_*.py` se añade a `.github/CODEOWNERS` bajo `@Crittan01` (mismo guardrail que evita "agregar gap + regenerar baseline en el mismo PR").
- Cada FF lleva su `tests/test_audit_<clase>.py` con una **fixture-bug** que prueba que el check detecta la regresión (anti-Clase-E sobre los propios guardrails — un check que dejó de detectar es la misma falla que combate).

## Secuencia de adopción (alineada a `data→security→compliance→inbox`, sin Goodhart)

1. **Primero el fix, luego el guardrail.** Cada FF se mergea **después** de cerrar los hallazgos P0/P1 de su clase (FF-A tras catálogo `variants`; FF-F tras `api/main.py` health; FF-G tras keys determinísticas). El baseline se congela en el estado **ya saneado**, no en el roto — el ratchet entonces solo puede mantener o mejorar.
2. **Orden por nivel**: FF-A (data/contrato) y FF-D (atomicidad) → FF-B/FF-C/FF-F (security/resilience) → FF-E (compliance cableado) → FF-G (inbox idempotencia).
3. El "score" de la auditoría **nunca entra a CI**. Lo que entra son los 7 mecanismos. La mejora es durable porque la *forma del bug* queda prohibida, no porque un número suba.

## INTERVENCION HUMANA REQUERIDA

- **RESPONSABLE**: founder (@Crittan01). **PASOS**: (1) aprobar añadir los 6 nuevos `audit_*.py` + baselines a `.github/CODEOWNERS`; (2) confirmar el `RPC_CONTRACT_MAX`/`BROAD_EXCEPT_MAX`/etc. iniciales tras congelar baseline post-fix. **INSUMOS**: este diseño + los baselines generados. **CRITERIO DE EXITO**: `validate.sh --ci` ejecuta los 7 bloques; cada uno con su test de auto-validación verde; ningún baseline regenerable sin review. **RIESGO si se omite**: un PR podría introducir un gap nuevo y regenerar el baseline en el mismo commit, vaciando el guardrail (el escenario exacto que motivó el CODEOWNERS de A6.2.4).

## VALIDAR (no asumido, declarado como pendiente)

- FF-A contrato RPC asume que **todas** las RPC del repo usan prefijo `out_` en `RETURNS TABLE`. Confirmado en `20260502000000` y `20260501000001`; **falta barrer las 87 migraciones** para descartar RPCs con OUT params sin prefijo (esos darían falso positivo). Mitigación: el parser solo enforça sobre RPCs cuyo OUT param set sea no vacío y derivable; las no parseables se exemptan con marker explícito.
- El conteo exacto de baseline de FF-C/FF-D/FF-G no se computó en esta sesión (requiere correr los scripts una vez escritos). Se declara como primer paso de implementación, no como dato cerrado.