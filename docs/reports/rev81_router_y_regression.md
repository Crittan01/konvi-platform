# Rev. 81 — Model router + regresión del bug del log

**Fecha**: 2026-04-30

## Items completados (rev. 81 batch 2)

### 1. E2E regression del bug del log conv 132f0dac

[tests/test_rev81_log_bug_regression.py](tests/test_rev81_log_bug_regression.py)

Fixture realista que reproduce el escenario del bug:
- Cart con `1x Coco 60g + 2x Lavanda 150g` ($82.000 subtotal).
- Shipping `$11.000` cotizado a Bogotá vía Servientrega Rápida.
- Total = `$93.000`.
- Address conjunto residencial (Torre 7, Apto 503, Torres de San Agustín).

Tests (6/6 OK):
- `test_summary_preserves_both_products`: el resumen muestra **ambos
  productos**, totales correctos, NO el bug `$26.000`.
- `test_summary_includes_full_address`: address con torre + apartamento
  presente.
- `test_shipping_inputs_use_real_cart_weights`: `compute_shipping_inputs`
  suma peso físico real (0.46 kg) y compute volumetric > 0.
- `test_summary_blocked_when_requires_requote`: si cart marcado para
  re-cotizar, summary devuelve None (forzar re-cotización).
- 2 tests adicionales sobre integridad de `_verified_ctx_from_cart`.

**Sirve como regresión permanente**: si futuras revisiones rompen el
cart-as-SoT, estos tests fallan y bloquean el deploy.

### 2. Model router (lite para FAQ, flash para transaccional)

[services/ai-orchestrator/llm_router.py](services/ai-orchestrator/llm_router.py)

Heurística determinística (cero costo extra, no llama LLM):

```
classify_intent(query, fsm_state, history) → "simple" | "transactional"

Reglas (en orden de prioridad):
  1. fsm_state ∈ {NEEDS_CONSENT, NEEDS_EMAIL, NEEDS_NAME,
                   NEEDS_DOCUMENT, NEEDS_DIRECTION,
                   READY_FOR_SUMMARY, AWAITING_ORDER_CONFIRMATION}
                                                       → transactional
  2. query matchea regex transaccional (comprar, pagar,
     link, cotizar, dirección, cédula, etc.)           → transactional
  3. history reciente (últimos 3 inbound) menciona
     intent transaccional                              → transactional
  4. default                                           → simple
```

**Modelos**:
- `simple` → primary `gemini-2.5-flash-lite`, fallback `flash`
- `transactional` → primary `flash`, fallback `flash-lite`

**Configurables vía .env**:
- `GEMINI_MODEL` (transactional primary)
- `GEMINI_FALLBACK_MODEL` (transactional fallback / simple primary)
- `GEMINI_SIMPLE_MODEL` (override explícito para simple)

**Estimación de costo**: 70% de turnos en chat-commerce son simples
(saludos, FAQ, catálogo, info producto). Routing reduce costos
**~50-60%** sin perder calidad transaccional.

### 3. Cascada con router cableada en orchestrator

[orchestrator.py:4102](services/ai-orchestrator/orchestrator.py#L4102):

```python
intent_class = classify_intent(content, display_state, history_for_prompt)
primary_model, fallback_model = model_pair_for(intent_class)
logger.info("[ROUTER] intent=%s primary=%s fallback=%s", ...)

cascade = generate_with_cascade(
    _invoke_gemini,
    primary_model=primary_model,
    fallback_model=fallback_model,
)
```

Logs estructurados `[ROUTER]` permiten medir distribución simple/transac
en producción (input para decisiones de tier paid de Gemini).

## Tests rev. 81 batch 2

| Test file | Cobertura | Resultado |
|---|---|---|
| `test_rev81_log_bug_regression.py` | Fixture del log + 6 asserts | 6/6 OK |
| `test_rev81_llm_router.py` | classify_intent, model_pair_for, defaults | 17/17 OK |
| `test_rev81_cascade_integration.py` (actualizado) | Verifica router cableado | 2/2 OK |

**Suite total**: 692 tests OK (rev. 80 = 664 + rev. 81 batch 1 = 5 +
rev. 81 batch 2 = 23). **Validate**: 13/13 OK. **Sanity**: 2/2 PASS.

## Pendientes descartados explícitamente

- **Multi-API-key rotation + circuit breaker**: el usuario decidió no
  implementarlo (no aplica con 1 tenant productivo). Cuando escale a
  5+ tenants, abrir rev. dedicada.
- **/schedule background agent**: el usuario prefiere trabajo manual.

## Observabilidad recomendada

Para validar el ahorro del router en producción, los logs de
orchestrator ya emiten `[ROUTER] intent=X primary=Y fallback=Z` y
`[GEMINI] model=W attempts=N`. Agregando una métrica simple:

```bash
# % de turnos simple vs transactional (últimas 24h):
grep "\[ROUTER\]" logs/orchestrator.log | \
  awk '{for(i=1;i<=NF;i++) if($i ~ /^intent=/) print $i}' | sort | uniq -c
```

Si simple representa <40%, el routing no está optimizando — revisar las
heurísticas. Si simple > 70%, ahorro de costo confirmado.
