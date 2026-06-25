I have enough verified evidence. The RPC result-to-key dataflow (line 80 `get_tenant_plan_capabilities` result is bound to `res` then indexed elsewhere) confirms FF-A's RPC linter needs cross-statement dataflow analysis, not the single-line `.rpc(...)["key"]` pattern it claims. The `get_transaction_with_resilience` reconciliation truly has no caller (FF-E anchor valid there), but `OutputValidator` does (FF-E anchor invalid there). Now I have the grounding to deliver the adversarial critique.

# Crítica Adversarial — Capa de Prevención (7 Fitness Functions) + Rúbrica + Roadmap

Verifiqué los anchors contra el árbol antes de juzgar. Varios load-bearing son **falsos o ya remediados**, lo que cambia el veredicto de fondo: el diseño es internamente coherente pero está anclado a una foto del código que ya no existe. Hallazgos priorizados.

---

## P0 — Anchors falsos: FFs que protegen bugs ya cerrados (riesgo de falsa sensación de seguridad)

Esto es el problema más grave porque contamina las tres entregas (estrategia, rúbrica, roadmap) y produce exactamente la Clase E que dice combatir: ceremonia que finge una garantía.

1. **FF-A catálogo ya está remediado.** `tool_id_referential_integrity.py:77` YA tiene `or item.get("variants")`. El mismatch productor↔consumidor que FF-A "previene" no existe hoy. El comentario del propio archivo (líneas 70-71) documenta el fix. Construir un pact contra `output real del productor` para este caso es válido como regresión, pero la estrategia lo presenta como bug **activo** ("falla hoy") — es falso. El único anchor de catálogo que justifica un pact es el guardrail de regresión, no el fix.

2. **FF-E afirma `OutputValidator` es código muerto. Es falso.** `orchestrator.py` lo invoca en 5 sitios (`OutputValidator().validate(...)` líneas 1975, 2117, etc.). Registrarlo en `GUARANTEED_CALLERS` como "garantía descableada" no detecta nada hoy; peor, si alguien refactoriza ese path legítimamente, FF-E da **falso positivo** y bloquea CI por un cambio correcto. El único anchor de FF-E que verifiqué como real es `get_transaction_with_resilience` (0 callers, reconciliación Wompi genuinamente descableada). **Un anchor real de cuatro citados.**

3. **C-75.3 de la rúbrica dice `grep X-Internal-Service-Secret tests/ = 0`. Es 3** (`tests/test_a11_dual_auth_integration.py`). El propio roadmap se contradice: lista "dual-auth tests ✓" como ya mergeado en Ola 0. La rúbrica afirma "ningún dominio con ruta S2S supera C-75.3 todavía" — falso. Un criterio de scoring que reporta 0 cuando son 3 es **no-falsable en la práctica**: nadie lo recomputó.

**Recomendación P0:** antes de escribir una sola FF, re-derivar TODOS los anchors contra HEAD actual (los 8 commits de Ola 0 ya movieron el suelo). Cada FF debe nacer con su anchor verificado en árbol o se elimina. Un guardrail anclado a un bug inexistente es deuda, no prevención.

---

## P1 — GOODHART residual: la rúbrica reintroduce el número que dice abolir

La estrategia es disciplinada ("el score no se cablea a CI"). La **rúbrica lo traiciona**:

4. **`score = min ponderado capeado por severidad` sigue siendo un número objetivo.** La regla "subir Orders de 62→85 exige exhibir el RPC + test + migración" es buena, pero el target-por-dominio (`62→85`, `68→90`) **es** una métrica que invita a optimizar. En cuanto un dominio tenga target 90, habrá presión para cerrar findings baratos que tocan la dimensión que capea, no los de mayor riesgo. El propio promedio "70 → 87.5" es el indicador Goodhart: nadie debería computar ese promedio si el principio es "no perseguir scores".

5. **El "mutation test" de C-95.1 es manual y por-dominio.** "Verificable inyectando el bug en un branch desechable" — esto no está en CI, depende de que un humano lo haga honestamente al certificar. Es precisamente el eslabón que un founder+AI bajo presión **saltará**. Un guardrail cuya validación-anti-no-op es manual tiene la misma fragilidad de la Clase E.

**Recomendación P1:** mantener la rúbrica como herramienta de **comunicación interna** (mapa de deuda), NO como gate. Borrar los targets numéricos por dominio del contrato de CI. Lo único que va a CI son los lints/pacts binarios. Si quieres anti-no-op real, el `test_audit_<clase>.py` con fixture-bug (que la estrategia SÍ propone) debe correr en la misma suite — no un "mutation check manual al certificar".

---

## P2 — OVER-ENGINEERING: 7 FFs + 6 scripts + módulo base + 7 fixtures + CODEOWNERS no lo sostiene founder+AI

6. **Proporcionalidad.** Cada FF añade: un `audit_*.py`, una entrada CSV baseline, un bloque en `validate.sh`, un `test_audit_*.py` con fixture-bug, una entrada CODEOWNERS, y una env var de ratchet. Eso es ~6 artefactos × 7 = ~40 piezas nuevas de infraestructura de meta-testing. El `audit_tenant_filter.py` base tomó hasta A6.2.7 (múltiples sub-fases) para llegar a 0 gaps de forma estable. Replicarlo 5 veces es un compromiso de mantenimiento que compite con producto — y la memoria del founder es explícita: **producto primero, calidad sobre esfuerzo pero no ceremonia sin ROI**.

7. **FF-A RPC linter es el más caro y el más frágil.** Su asunción declarada (`todas las RPC usan out_`) ya la **refuté**: `RETURNS TABLE(id uuid, title text, content text, ...)` existe sin prefijo. Peor, el dataflow real no es `.rpc(...)["key"]` en una línea — verifiqué que el patrón dominante es `res = supabase.rpc(...)` y el `res["key"]` ocurre líneas/funciones después (63 call sites, ninguno con el índice en la misma línea en mi muestra). Un linter AST que necesita seguir la variable `res` a través de statements es un mini-análisis de dataflow — semanas de trabajo y fuente garantizada de falsos positivos. **No es "clon estructural de audit_tenant_filter" — es una bestia distinta.**

**Recomendación P2 (recorte concreto, ordenado por ROI/costo):**
- **Construir solo 2:** FF-C (`audit_broad_except.py`, 712 `except Exception` en services es señal real y transversal) y la extensión del **pact de catálogo/enum** (binario, barato, anclado a la constante compartida). Estos dos cubren las dos clases más extendidas con el menor riesgo de FP.
- **Degradar FF-A-RPC, FF-D, FF-E, FF-G a `grep`-tests simples** dentro de pytest, no scripts AST con baseline/CODEOWNERS. Ej: FF-G = un test que falla si `uuid4()` aparece en la misma expresión que `Idempotency-Key` (regex sobre el árbol, 10 líneas, sin ratchet CSV). El ratchet con baseline CSV + CODEOWNERS solo se justifica cuando el conteo es alto y decreciente (tenant_filter: 198→0). Para FF-G/FF-F el conteo objetivo es 0-3: un test binario basta.
- **No extraer `_ast_lint_base.py` todavía.** Es DRY prematuro: hasta no tener 2 linters reales funcionando no sabes qué abstracción comparten. Extraer base de 1 ejemplo es especulativo.

---

## P3 — FALSOS POSITIVOS que erosionarían confianza en CI

8. **FF-C regla 2 (`except Exception` que retorna default sin métrica).** "¿hay un `Call` a `capture_exception`/`metric`/`logger.error` con `exc_info`?" — esto genera FP masivos. Hay 712 `except Exception` legítimos (cleanup, lookups best-effort como `consume_by_cart:196` que ya hace `logger.warning`). Forzar `metric` o `exc_info` en cada uno inundará el baseline con cientos de gaps, el founder regenerará el CSV una vez, y el guardrail muere como no-op — el escenario que CODEOWNERS dice prevenir, autoinfligido por un check demasiado celoso. **La regla "solo `logger.warning` sin métrica = fail-open" es un juicio semántico disfrazado de binario** (ADR-0024 lo prohíbe: distinguir "fail-open inseguro" de "best-effort legítimo" NO es verificación binaria).

9. **FF-D `.eq("version", ...)` como proxy de atomicidad** producirá FP en inserts legítimos sin versioning y FN en RMW que sí usan version pero en tabla no listada. La señal "tabla ∈ ATOMIC_ONLY_TABLES sin `.eq(version)`" no distingue un `UPDATE` de metadata inocuo de un lost-update real.

10. **FF-E sobre `OutputValidator`** (ya cubierto en P0) es el FP arquetípico: bloquea refactors correctos de código vivo.

**Recomendación P3:** Para FF-C, invertir la regla a algo **verdaderamente binario y de bajo FP**: detectar SOLO `except (..., KeyError|NameError|TypeError|AttributeError, ...)` que NO re-raisea **y** está en el set `MUST_FAIL_CLOSED` (consent/opt-out/tenant-resolution). Eso es ~decenas de sitios, no 712, y cada uno es un bug real (el `KeyError: tenant_id` del sweep, el `NameError sys`). Olvidar la regla 2 (métrica) — es inauditable sin semántica.

---

## Veredicto

| Entrega | Diseño conceptual | Anclaje a la realidad | Sostenibilidad founder+AI |
|---|---|---|---|
| Estrategia 7 FF | Sólida (anti-Goodhart explícito, reúsa infra) | **Débil** — ≥3 anchors falsos/stale | **Baja** — 40 artefactos, FF-A irrealista |
| Rúbrica | Buena como mapa | Stale (C-75.3 = 0 es 3) | Media — reintroduce número objetivo |
| Roadmap | Buen orden por clase/nivel | Mejor anclado (Ola 0 honesta) | Media-alta si se recorta Ola 2 |

**Lo que SÍ resiste el ataque:** el principio "prohíbe la forma del bug, no el número"; la secuencia data→security→compliance; gate `[FOUNDER-MIGRATION]` para IDOR (verifiqué: `consume/release/extend` sin `p_tenant_id` es IDOR real); poner WMP-1 reconciliación en Ola 1 (verifiqué: `get_transaction_with_resilience` existe sin caller — quick-win legítimo).

**Lo que NO resiste:**
- Construir 7 FFs. Construir **2** (broad-except acotado a MUST_FAIL_CLOSED + pact catálogo/enum). El resto, tests `grep`/AST simples en pytest sin maquinaria de baseline.
- FF-A RPC linter como "clon estructural" — es dataflow analysis, semanas, alta tasa FP. **Recortar o reducir a pact manual de los ~3 RPCs críticos.**
- La rúbrica como gate. Degradar a documento de comunicación.
- Re-anclar TODO contra HEAD antes de codear: Ola 0 movió el suelo bajo los anchors.

**Riesgo central no mitigado:** la mayor amenaza a la durabilidad no es que la Clase A reaparezca — es que 40 piezas de meta-infraestructura con FP generen ruido, el founder regenere baselines para desbloquear PRs, y los 7 guardrails colapsen a no-ops simultáneamente. Eso sería peor que no tenerlos, porque darían la falsa señal "CI me protege". **Menos guardrails, binarios de verdad, con bajísimo FP — sostenibles — superan a 7 guardrails ceremoniales.**