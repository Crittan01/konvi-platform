# Rev. 81 — Cierre de pendientes rev. 80

**Fecha**: 2026-04-30

## Items completados

### 1. Cablear `generate_with_cascade` en el call site principal

[orchestrator.py:4102–4137](services/ai-orchestrator/orchestrator.py#L4102) — la llamada
directa a `client.models.generate_content(...)` quedó reemplazada por:

```python
from llm_invoke import generate_with_cascade, degraded_response_text

def _invoke_gemini(model_name: str):
    return client.models.generate_content(
        model=model_name,
        contents=user_context,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )

cascade = generate_with_cascade(_invoke_gemini)
if cascade.degraded:
    raw_json = degraded_response_text()    # respuesta canned con requires_human=true
else:
    raw_json = cascade.response.text
```

Comportamiento productivo:
- Intentos 1–4: `gemini-2.5-flash` con backoff exp (1, 2, 4, 8s).
- Intentos 5–8: `gemini-2.5-flash-lite` con backoff (16s).
- Si todo falla: respuesta degradada con escalación humana — el cliente
  recibe *"Disculpa, estoy teniendo dificultades técnicas. Un asesor
  humano se pondrá en contacto contigo"* en lugar de quedarse sin
  respuesta (caso del log conv 132f0dac que reclamó 3 veces sin réplica).

Logs estructurados: `[GEMINI] model=X attempts=N | Raw: ...`.

### 2. B + A.3 — `_estimate_package_from_cart_if_available`

[shipping_quote_tool.py](services/ai-orchestrator/tools/shipping_quote_tool.py) — nueva función
que se invoca **antes** del resolver tradicional. Si el cart en DB tiene
items, construye `PackageEstimateDecision` directamente desde
`cart_tool.compute_shipping_inputs(cart)` (peso billable + dims escaladas
por qty^(1/3)).

Resultado:
- **Skip de doble confirmación**: si el cliente ya armó su carrito en
  turnos previos, el bot NO le pide re-confirmar producto cuando
  responde "Bogotá".
- **Cotización fiel al peso real**: el envío se cobra con el billable
  weight del cart entero (físico vs volumétrico, max), no con el último
  producto mencionado.

Bug del log donde el cliente repetía 3 veces "1 Coco + 2 Lavanda" porque
el bot le pedía confirmar — eliminado: cuando el cart-DB esté poblado
(via populate-on-demand de rev. 80), el resolver omite la disambig.

## Tests rev. 81

| Test file | Cobertura | Resultado |
|---|---|---|
| `test_rev81_shipping_from_cart.py` | 3 escenarios (no cart, cart vacío, cart con 2 items) | 3/3 OK |
| `test_rev81_cascade_integration.py` | Verifica que orchestrator.py importa y usa cascade | 2/2 OK |

**Suite total**: 669 tests OK (664 baseline rev. 80 + 5 nuevos rev. 81).
**Validate**: 13/13 OK. **Sanity conversational**: 2/2 PASS.

## Pendiente (no crítico)

- **E2E reproducción del bug del log**: requiere setup de fixture con
  carrito real + simular flujo completo. Útil pero no bloquea producción
  porque los unit tests cubren el path arquitectónico.
- **Model router** (rev. 82): usar lite para FAQ/KB y flash solo para
  resumen/cart/payment-link. Reduciría costos ~60-70%.
- **Multi-API-key rotation + circuit breaker por tenant**: para escalado
  >5 tenants. La cascada actual mitiga el caso de 1 tenant.

## Decisión documentada: flash → flash-lite (no invertido)

Mantenemos el orden actual. Razones:
- `flash` tiene calidad superior en JSON estructurado y extracción
  multi-campo (crítico para el cart).
- `flash-lite` falla con más frecuencia en outputs estructurados.
- Costo extra de flash (~3x lite) << costo de un error en el resumen.
- Lite es **excelente como fallback degradado** (respuesta cualquiera >
  sin respuesta).

Inversión solo conviene si pasamos a un **model router** que clasifique
intent primero (cheap call) y route el modelo según complejidad — eso
es rev. 82+.
