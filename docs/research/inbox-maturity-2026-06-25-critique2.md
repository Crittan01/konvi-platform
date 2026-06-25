The FF-E anchor is **confirmed dead** — `get_transaction_with_resilience` appears only in its own definition file and a comment literally saying "son API INTERNA lista para callers" (i.e., no caller, by the author's own admission). The self-validation pattern (`test_audit_tenant_filter.py`, 24 tests) exists, so that part of the design is sound. I have enough grounding to write the adversarial critique.

---

# Crítica adversarial — Capa de prevención + Roadmap del Inbox

**TL;DR del EM:** El diseño es intelectualmente sólido y el principio anti-Goodhart es correcto. Pero **dos de las siete fitness functions están construidas sobre anclas falsas que verifiqué en el árbol**, el roadmap subestima sistemáticamente el costo de coordinación migración↔deploy, y hay un punto ciego de durabilidad que invalida la premisa central: *quién mantiene los 7 guardrails cuando el founder está en otra cosa 3 meses*. Prioriza FF-C y el pact de catálogo; **descarta o reescribe FF-A-RPC**; no construyas 7 guardrails de golpe.

---

## SECCIÓN 1 — Hallazgos por anclaje (verificados en árbol, no opinión)

### H1 [BLOQUEANTE] FF-A (contrato RPC) descansa sobre una convención que NO existe

El diseño afirma que `audit_rpc_contract.py` extrae OUT params asumiendo el prefijo `out_`, y degrada a "las no parseables se exemptan con marker". Verificado:

> **Solo 2 de 17 migraciones con `RETURNS TABLE` usan el prefijo `out_`** (`20260501000001`, `20260502000000`). Las otras 15 usan columnas desnudas: `id uuid`, `title text`, `content text`...

Consecuencia real, no la que el "VALIDAR" del diseño admite:
- No es "falta barrer 87 migraciones por si acaso". Es que **la convención `out_` es la excepción (12%), no la regla**. El linter no puede usar el prefijo como discriminador de "esto es un OUT param".
- El fallback propuesto ("exemptar las no parseables") **vacía el check para el 88% de los RPCs** → queda protegiendo exactamente los 2 RPCs que ya fueron arreglados a mano esta sesión. Es un guardrail que solo cubre el caso ya cerrado: **la propia Clase E que el diseño dice combatir** (código que finge garantía).
- Para que FF-A-RPC fuera real habría que parsear el cuerpo completo de cada función PL/pgSQL y mapear `RETURNS TABLE(col type, ...)` literal por posición — eso es un mini-parser SQL, no "regex ya probado en `discover_tenant_scoped_tables_from_migrations`". El diseño infló la reutilización.

**Ajuste:** Partir FF-A en dos. El pact de catálogo (constante única `CATALOG_VARIANTS_KEY` contra output real de `get_tenant_catalog`) **es ejecutable y de alto valor — construir**. El contrato RPC genérico **no es construible con el esfuerzo declarado**; reemplazar por un test puntual que afirme las return-keys de los ~3 RPCs que callers indexan por string (CART add, stock reserve), mantenido a mano. No vendas eso como "linter AST sobre todas las RPC".

### H2 [ALTO] FF-A invierte la dirección del pact existente, pero el pact existente NO llama productores

El diseño dice "extiende `test_coherence_pact.py` pero invierte la dirección: en vez de fixtures estáticas, llama a la función productora". Verificado el mecanismo real:

> `test_coherence_pact.py` hace `set(Model.model_fields) ⊆ set(columnas_del_fixture_JSON)`. **Es puramente estático**: compara campos Pydantic contra `tests/fixtures/db_schema_canonical.json` (volcado offline). **Nunca instancia ni invoca un productor.** No hay infraestructura de "llamar a `get_tenant_catalog` con fixture mínimo".

O sea: FF-A no "extiende" el pact, **inventa un mecanismo nuevo** (invocar productores en test, montar fixtures de entrada mínimos, capturar `set(keys())` del output). Eso es legítimo pero contradice la tesis vendedora del documento ("cada FF extiende uno de dos mecanismos ya probados, no inventa infraestructura nueva"). Para catálogo necesitas instanciar el tool con un cliente Supabase mockeado o fixture de DB → **eso sí es infra nueva y frágil** (¿mockeas Supabase? entonces vuelves al riesgo de "mock con forma rota" que el diseño dice eliminar).

**Ajuste:** Sé honesto sobre qué es extensión vs invención. El pact de catálogo realista no llama al productor con DB real (costaría una DB efímera por test); llama con un **fixture de fila de catálogo que vive en el mismo `db_schema_canonical.json`** y verifica que productor y consumidor leen la misma constante de key. Sigue siendo estático — y está bien — pero deja de prometer "output real del productor".

### H3 [MEDIO] Rutas de archivo equivocadas en todo el diseño → señal de verificación incompleta

El diseño cita `tools/catalog_tool.py`, `agentic/invariants/...`, `worker.py:953`. En el árbol todo cuelga de `services/ai-orchestrator/`:
- `services/ai-orchestrator/agentic/invariants/tool_id_referential_integrity.py`
- `services/ai-orchestrator/agentic/dispatcher.py` (confirmado: **71** `except Exception`, el dato de FF-C es correcto)
- `services/ai-orchestrator/tools/shipping_quote_tool.py:1345` (confirmado: `f"inbox-quote-{uuid.uuid4()}"`, FF-G correcto)

No es cosmético: las rutas equivocadas indican que el "I have verified all seven class anchors against the tree" del preámbulo **no fue uniforme**. FF-C y FF-G están bien anclados (los verifiqué). FF-A-RPC no. Trata cada FF como independientemente verificada, no como bloque.

### H4 [CONFIRMA] FF-E está bien anclado — y es el de mayor valor latente

Verifiqué `get_transaction_with_resilience`: aparece **solo en su archivo de definición** y en un comentario que dice literalmente *"son API INTERNA lista para callers"*. Es decir, el propio autor documentó que NO tiene caller. FF-E (lint "garantía registrada sin caller") es **el guardrail mejor justificado del set** y el menos costoso (un callgraph estático de nombres). Subir su prioridad por encima de FF-A.

---

## SECCIÓN 2 — REALISMO (founder + 1 agente, sin quemarse)

### H5 [ALTO] La Ola 2 ("construir las 7 fitness functions") es la trampa de scope clásica

El roadmap pone "Fitness anti-Clase-A" como Ola 2 esfuerzo **M**. Pero el documento de prevención describe **7 scripts nuevos + 1 módulo base extraído + 7 tests de auto-validación + 7 baselines + 7 entradas CODEOWNERS + 7 bloques en validate.sh**. Eso no es M; es la mitad de un finiquito.

- Extraer `_ast_lint_base.py` de un archivo de **524 líneas** que hoy es monolítico (verificado: `FileVisitor`, `_collect_chain_methods`, ratchet, todo en un archivo) **toca el único guardrail que YA funciona en CI**. Refactorizar el linter de aislamiento multi-tenant para "compartir base" arriesga regresión en el check con `BASELINE_MAX=0` que protege la propiedad más crítica del sistema. **Riesgo/beneficio pésimo.** Copiar-pegar 200 líneas 6 veces es feo pero seguro; el DRY aquí compra deuda peor que la que evita.

**Ajuste:** No extraigas base compartida en la primera pasada. Construye **2 guardrails reales** (FF-C broad-except + pact-catálogo), cada uno como copia independiente. Si tras 2 ves un patrón estable, extraes base. "Construir 7 + framework común" en una ola es exactamente el plan de remediación que este EM ha visto fracasar: se mergea el 40%, el resto queda medio-hecho y se pudre.

### H6 [MEDIO] Cada AST linter nuevo recorre 217 archivos .py → costo CI acumulativo

`validate.sh --ci` ya corre pytest+coverage (`coverage run --source=services`), tsc, eslint, build, audit_tenant_filter. Sumar 6 walks AST sobre 217 archivos cada uno no es gratis en wall-clock de CI ni en el loop local del agente. Con founder+1 agente, **un `validate.sh` que tarda 6 min mata el ciclo de iteración**. No está presupuestado en el roadmap.

**Ajuste:** Un solo pase AST que aplique todas las reglas de visitor (un `ast.parse` por archivo, N visitors), no N scripts que cada uno re-parsea. Esto sí justifica base común — pero por **performance**, no por DRY estético. Reordena el argumento.

### H7 [MEDIO] La premisa "Ola 0 = Clase A CERRADA" no está validada en runtime

El roadmap declara Ola 0 cerrada con 8 commits. Verifiqué que los commits existen (`f072ad4f`, `bca56683`, etc.). Pero la propia memoria del proyecto (`feedback_no_static_uat`, `feedback_analytical_uat`) exige **UAT dinámica online turn-a-turn** antes de declarar cerrado, y el roadmap solo marca eso para olas `[HOT-PATH]`. Los fixes de Clase A tocan catálogo y FSM — **eso es hot-path de conversación**. Declararlos cerrados por "test verde + commit" viola la regla del propio founder.

**Ajuste:** Ola 0 no está "CERRADA", está "code-complete, UAT-pendiente". El gate de Ola 2 (construir la fitness function) debería incluir: *la prueba negativa (re-introducir el bug original y ver CI rojo) corre contra el bug REAL, reproducido en UAT live*, no contra una fixture-bug sintética.

---

## SECCIÓN 3 — DURABILIDAD (¿se queda la mejora en 3 meses?)

### H8 [BLOQUEANTE para la tesis] El punto ciego central: nadie mantiene 7 ratchets

La tesis entera es "la forma del bug queda prohibida". Pero un ratchet decreciente con baseline CSV **requiere un humano que entienda por qué un gap es legítimo vs regresión** cada vez que CI se pone rojo. Con founder+1 agente:

- 7 baselines × decisiones de exempt-marker = 7 superficies donde, bajo presión de entrega, **la salida de menor resistencia es subir el `MAX` o añadir `# exempt`** sin análisis. El CODEOWNERS (verificado: existe, cubre `audit_tenant_filter.py` + su baseline) protege contra *regenerar baseline en el mismo PR*, pero **no protege contra el founder aprobándose su propio bypass** — él es el único CODEOWNER (`@Crittan01`).
- Un guardrail que solo una persona puede revisar, y esa persona es la que también tiene presión de shippear, **se degrada a no-op en 3 meses**. Esa es la Clase E aplicada a los propios guardrails — el diseño la nombra pero no la resuelve, porque la solución (segundo revisor) no existe en un equipo de 1.

**Ajuste (lo que falta para irreversibilidad):**
1. **Consolidar a ≤3 guardrails**, no 7. Menos superficies de bypass = más durable. Prioriza por blast-radius: broad-except fail-open (C), catálogo (A), idempotencia (G). Los demás (D/E/F) son tests puntuales, no ratchets con baseline que mantener.
2. Para los ratchets que sí queden, **el exempt-marker debe exigir un finding-id del audit** (`# broad_except:exempt:WMP-3`), no prosa libre. Hace auditable a futuro por qué se eximió.
3. El test de auto-validación (fixture-bug → check detecta) **debe correr en CI siempre**, no como artefacto opcional. Verifiqué que `test_audit_tenant_filter.py` existe con 24 tests — ese patrón es el que evita el no-op silencioso. **Es la parte más durable del diseño; replícala religiosamente.**

### H9 [ALTO] Baselines no computados = el roadmap promete números que no existen

El "VALIDAR" admite que `BROAD_EXCEPT_MAX`/`ATOMIC_MUTATION_MAX`/`IDEMPOTENCY_MAX` no se computaron. Pero la rúbrica de scoring y el DoD de olas **dependen de esos números**. No puedes congelar un baseline "post-fix" (Ola 1) si no sabes el baseline "pre-fix". El orden "primero el fix, luego el guardrail" suena bien pero **significa que el guardrail no protege nada durante la ventana en que estás haciendo el fix** — y con un solo agente, esa ventana son semanas.

**Ajuste:** Invierte para C/D/G: congela el baseline en el estado ROTO **ahora** (con ratchet decreciente), y cada fix baja el número. Así el guardrail está activo desde el día 1 e impide *nuevos* gaps mientras arreglas los viejos. El diseño eligió lo contrario y deja un hueco temporal grande.

---

## SECCIÓN 4 — VENTANAS DE INCONSISTENCIA migración↔deploy

### H10 [ALTO — riesgo de producción real] Olas 3/5/6 tienen ordering hazard no mitigado

El roadmap agrupa migraciones "en lotes para minimizar ventanas de autorización". **Eso optimiza la variable equivocada.** El riesgo no es el número de ventanas; es la **coordinación migración↔código** contra una DB compartida con drift (memoria `feedback_supabase_migrations`).

Ejemplos concretos de ventana peligrosa:
- **Ola 3 IDOR:** añadir `p_tenant_id` a RPCs `consume/release/extend` **cambia la firma**. Si la migración (nueva firma) se aplica a prod **antes** del deploy del código que pasa el nuevo argumento → **todos los callers rompen en runtime** (función no existe con la firma vieja, o peor, Postgres resuelve la sobrecarga incorrecta). Verifiqué que hoy operan solo sobre `p_reservation_id`. Esto es un hot-path de reserva de stock: la ventana = ventas caídas.
- **Ola 5 `rpc_create_order_with_items`:** orden de despliegue obligatorio = migración primero (función nueva, aditiva, no rompe), deploy después. Pero `uniq_active_order_per_conv` parcial **puede rechazar inserts que el código viejo aún intenta** durante la ventana → órdenes fallando entre migración y deploy.

El roadmap no especifica **dirección de despliegue por migración** (expand-then-contract). Agruparlas en lote **empeora** esto: un lote grande de migraciones aplicadas de una vez contra código que aún no las espera = ventana de inconsistencia máxima.

**Ajuste:**
- Para cada migración, clasificar **aditiva (segura aplicar antes)** vs **restrictiva/firma-cambiante (requiere expand-contract)**. Las de firma (IDOR `p_tenant_id`) deben ir como **sobrecarga nueva**, no reemplazo: crea `consume(p_reservation_id, p_tenant_id)` coexistiendo con la vieja, migra callers, luego dropea la vieja en migración posterior. Nunca cambies firma in-place contra prod con drift.
- **Lotes = MALA idea aquí.** Migraciones restrictivas deben ir 1:1 con su deploy de código, en orden expand→migrate-callers→contract. Un lote de 6 viola esto por construcción.
- El DoD de Ola 3/5/6 debe incluir explícitamente: *"aplicada en orden expand-contract, verificada en prod que los callers viejos no rompen durante la ventana"*.

---

## SECCIÓN 5 — PUNTOS CIEGOS (clases/riesgos no cubiertos)

### H11 [MEDIO] Ningún guardrail cubre la regresión de los FIXES de Ola 0 mismos

Las 7 FF previenen reintroducir las clases A-G *genéricamente*, pero los 8 fixes específicos de Ola 0 (FSM `human_takeover`, sweep `tenant_id`, Wompi monto/moneda) **no tienen test de regresión nombrado en el roadmap**. FF-A pact-catálogo cubre el de catálogo; ¿qué cubre el de Wompi monto/moneda? Si alguien revierte `98230224` (Wompi valida monto antes de confirmar), ¿qué CI lo atrapa? Nada en las 7 FF. **Gap directo.**

### H12 [MEDIO] El concurrency/race está subdimensionado a "donde aplique"

C-95.2 pide "race real contra Postgres efímero" pero solo en Tier 3 / nivel 95, y el roadmap lo mete en Ola 5 DoD vagamente. El oversell (INV stock) y el doble-envío (ORCH-03, W-03 claim atómico) son **los bugs de mayor severidad financiera** y son intrínsecamente de concurrencia — un test secuencial no los detecta. No hay infra de "Postgres efímero + N requests concurrentes" en el repo hoy (no la encontré). **Eso es infra nueva sustancial no presupuestada**, y sin ella los DoD de oversell/doble-envío son no-verificables.

### H13 [BAJO] FF-D (atomic mutation) usa heurística `version` que puede dar falsos negativos

FF-D detecta RMW por "no hay `.eq("version", ...)` en la chain". Pero CAS también puede hacerse con `.eq("updated_at", ...)` o un `WHERE stock >= qty` guard, o vía RPC con nombre no-`cart_*`. La regla binaria propuesta **deja pasar mutaciones atómicas con patrón distinto (falso positivo → ruido) y RMW disfrazados (falso negativo → el bug que busca)**. Es el riesgo ADR-0024 invertido: demasiado binaria para una propiedad semántica. FF-D es el más débil del set después de FF-A-RPC.

---

## VEREDICTO Y RE-PLAN PRIORIZADO

| # | Acción | Por qué |
|---|---|---|
| 1 | **Construir FF-C (broad-except) + pact-catálogo como 2 scripts independientes.** Sin base común aún. | Anclas verificadas (71 except en dispatcher; `variants` real). Máximo blast-radius, mínimo riesgo. |
| 2 | **Congelar baselines de C/D/G en estado ROTO ahora** (ratchet decreciente), no post-fix. | Cierra el hueco temporal H9; guardrail activo desde día 1. |
| 3 | **Reescribir FF-A-RPC → test puntual de ~3 RPCs indexados por string.** Matar el "linter genérico de OUT params". | Convención `out_` existe en 12% de RPCs (H1). El check genérico es no-op disfrazado. |
| 4 | **Subir FF-E a prioridad alta** (callgraph "garantía sin caller"). | Mejor anclado del set (H4); el propio código admite "sin caller". Barato. |
| 5 | **Reclasificar migraciones por expand-contract; prohibir lotes para las restrictivas.** | H10: firma-cambiante in-place contra prod con drift = ventas caídas. |
| 6 | **Añadir test de regresión nominal por cada fix de Ola 0** (no solo prevención genérica). | H11: revertir Wompi/sweep no rompe ningún CI hoy. |
| 7 | **NO extraer `_ast_lint_base.py` hasta tener ≥3 linters estables.** Si se extrae, justificar por perf (un pase AST), no DRY. | H5/H6: refactorizar el linter `BASELINE_MAX=0` que ya funciona = regresión en la propiedad más crítica. |
| 8 | **Decidir explícitamente: ≤3 ratchets, no 7.** D/E/F como tests puntuales sin baseline. | H8: con 1 CODEOWNER, cada ratchet es una superficie de auto-bypass. Menos = más durable. |

**Lo que el diseño acierta y debe preservarse:** el principio anti-Goodhart (`min` ponderado capeado por severidad, no promedio); el test de auto-validación con fixture-bug (verificado `test_audit_tenant_filter.py`, 24 tests — replícalo); el "primero el fix, luego el guardrail" **para A** (no para C/D/G); CODEOWNERS sobre baselines.

**La mentira por omisión más peligrosa del documento:** vende "extiende dos mecanismos probados, no inventa infra" cuando FF-A, FF-B y el smoke de FF-F **sí inventan infra** (invocar productores, registro AST de deps S2S, arrancar app de test). Eso no las invalida, pero el roadmap las presupuesta como "M, extensión barata" cuando son construcción nueva. Re-presupuestar antes de comprometer la Ola 2.

Archivos verificados (absolutos): `/home/ansible/workspaces/konvi-platform/scripts/audit_tenant_filter.py` (524 líneas, monolítico), `/home/ansible/workspaces/konvi-platform/tests/test_coherence_pact.py` (estático, NO llama productores), `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/dispatcher.py` (71 except), `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/tools/shipping_quote_tool.py:1345` (uuid4 confirmado), `/home/ansible/workspaces/konvi-platform/services/api/integrations/wompi_client.py:19` (dead code confirmado por comentario), `/home/ansible/workspaces/konvi-platform/.github/CODEOWNERS` (1 solo owner @Crittan01).