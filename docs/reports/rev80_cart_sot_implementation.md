# Rev. 80 — Cart-en-DB SoT + Cascada LLM (Implementación parcial)

**Fecha**: 2026-04-30
**Bug detonante**: log conv 132f0dac (2026-04-30 14:48-15:04) — el resumen
WhatsApp mostró `1x Coco $26.000` cuando el carrito real era `1x Coco
60g + 2x Lavanda 150g = $93.000`. Cliente reclamó 3 veces sin respuesta.

---

## Resumen ejecutivo

| Item del plan | Estado | Cobertura |
|---|---|---|
| **Pre-flight schema** | ✅ | 0 variations con dims NULL (34/34) |
| **Migración `requires_requote`** | ✅ Aplicada en remote + ledger sync | 20260505000000 |
| **A.1 cart_tool.py** | ✅ Implementado + 12 tests | 8 funciones (ensure/add/update/remove/get/compute_shipping/set_meta/invalidate) |
| **A.4 Summary lee de DB** | ✅ Implementado + 5 tests | Cubre el bug `$26.000 → $93.000` |
| **A.2 Populate-on-demand** | ✅ Implementado | Cart se puebla automático antes del resumen |
| **C llm_invoke cascada** | ✅ Implementado + 14 tests | flash → flash-lite → respuesta degradada |
| **A.3 shipping_quote_tool refactor** | ⏳ Out-of-scope esta sesión | Para rev. 81 |
| **B skip doble confirmación** | ⏳ Out-of-scope esta sesión | Para rev. 81 |

**Suite**: 664 tests OK (633 baseline + 31 nuevos rev. 80) · validate 13/13.

---

## A.1 cart_tool.py — funciones expuestas

[services/ai-orchestrator/tools/cart_tool.py](services/ai-orchestrator/tools/cart_tool.py)

| Función | Propósito |
|---|---|
| `ensure_cart` | Devuelve cart `open` o lo crea (idempotente, asocia contact_id) |
| `add_item` | Invoca RPC `cart_add_item` (UPSERT atómico) + invalida shipping |
| `update_item_quantity` | DELETE existente + add_item con qty nueva |
| `remove_item` | DELETE + recálculo subtotal + invalida shipping |
| `get_cart_with_items` | SELECT JOIN con `product_variations` (incluye dims) |
| `compute_shipping_inputs` | Peso físico + volumétrico + billable + package_dims |
| `set_shipping_meta` | Persiste rate Envia + recalcula totals + clear requires_requote |
| `invalidate_shipping` | Set `requires_requote=true` + reset `shipping_cents=0` (preserva address) |

**Cálculo volumétrico canónico**: `volumetric_kg = (L_eff × W_eff × H_eff) / 5000`,
donde `dim_eff = base × qty^(1/3)` (heurística de packing realista).
**Billable weight** = `max(physical_kg, volumetric_kg)`.

Tests: [tests/test_rev80_cart_tool.py](tests/test_rev80_cart_tool.py) — 12/12 OK.

---

## A.4 Summary determinístico desde DB

[orchestrator.py:1719 `_build_order_summary_text`](services/ai-orchestrator/orchestrator.py#L1719) ahora acepta
`cart_from_db: Optional[dict]` como **fuente prioritaria**. Si el cart en DB
tiene items y `requires_requote=False`, construye el `verified_ctx` directamente
desde DB. El history-parsing queda como fallback (deprecado rev. 80 pero
preservado por seguridad).

Nueva función helper: `_verified_ctx_from_cart(cart) -> dict | None`.

**Caso de prueba reproducible** (test `test_summary_uses_cart_when_provided`):
- Cart con 2 items: `1x Coco $18k + 2x Lavanda $64k`, shipping $11k.
- Resumen contiene **ambos productos** y total $93.000 — NO $26.000.

Tests: [tests/test_rev80_summary_from_db.py](tests/test_rev80_summary_from_db.py) — 5/5 OK.

---

## A.2 Populate-on-demand

En `orchestrator.py` justo antes de generar el resumen
(transición `NEEDS_X → READY_FOR_SUMMARY`):

```
1. get_cart_with_items(supabase, conversation_id, tenant_id)
2. Si cart vacío:
   - Resolver from history → ctx_items
   - ensure_cart + add_item por cada item resuelto
   - Re-leer cart (ahora poblado)
3. Pasar cart_for_summary a _build_order_summary_text
```

**Por qué importa**: en el bug del log, el último mensaje pre-resumen era
*"Perfecto, con envío Rápida"* — el resolver perdía los productos al
parsear solo los últimos turnos. Con populate-on-demand, los items se
persisten en cart cuando el resolver SÍ los encuentra (turn anterior),
y el resumen los lee de DB en turnos posteriores aunque el resolver ya
no los detecte.

---

## C — Cascada LLM (resiliencia 503)

[services/ai-orchestrator/llm_invoke.py](services/ai-orchestrator/llm_invoke.py)

`generate_with_cascade(invoke_fn, ...)`:

- **Intentos 1–4**: `gemini-2.5-flash` (primario) con backoff exponencial
  truncado (1s, 2s, 4s, 8s).
- **Intentos 5–7**: switch a `gemini-2.5-flash-lite` (fallback) con
  backoff (16s).
- **Intento 8**: si todo falla → respuesta degradada con
  `requires_human=true`, mensaje: *"Disculpa, estoy teniendo dificultades
  técnicas. En un momento un asesor humano se pondrá en contacto contigo"*.

**Detección de transientes**: 503/504/429, "unavailable", "deadline
exceeded", "resource_exhausted", "rate limit", "too many requests",
"timeout", "internal", "connection", "high demand".

Errores no-transitorios (4xx, schema-rotos) se re-lanzan al caller —
no reintentamos bugs.

Configuración via `.env`:
- `GEMINI_MODEL` (default `gemini-2.5-flash`)
- `GEMINI_FALLBACK_MODEL` (default `gemini-2.5-flash-lite`)
- `GEMINI_MAX_RETRIES` (default 8)
- `GEMINI_FALLBACK_AFTER` (default 4)

Tests: [tests/test_rev80_llm_cascade.py](tests/test_rev80_llm_cascade.py) — 14/14 OK.

**Importante**: el wrapper está implementado y testeado, **pero la integración
en orchestrator.py:4057 (sustituir la llamada directa) queda pendiente
para próxima sesión**, junto con A.3 y B. Esto es porque el call site
construye el `config=GenerateContentConfig(...)` con system_prompt que
varía por turno; el refactor a closure-based invoke requiere cuidado y
testing E2E.

---

## Pendientes para rev. 81

| # | Item | Prioridad |
|---|---|---|
| 1 | Integrar `generate_with_cascade` en orchestrator.py:4057 | M |
| 2 | A.3 — `shipping_quote_tool.quote_with_cart` (lee dims de cart_items) | M |
| 3 | B — Skip doble confirmación cuando cart en DB ya tiene items | M |
| 4 | E2E test: reproducir flujo del log y verificar resumen $93.000 | M |
| 5 | Multi-API-key rotation + circuit breaker por tenant (rev. 79 D) | L |

---

## Migración aplicada

`supabase/migrations/20260505000000_carts_requires_requote.sql`:

```sql
ALTER TABLE public.conversation_carts
  ADD COLUMN IF NOT EXISTS requires_requote BOOLEAN NOT NULL DEFAULT false;
```

Aplicada vía `supabase db query --linked -f` + `migration repair --status
applied 20260505000000`. Ledger sync verificado.

---

## Verificación reproducible

```bash
# Suite completa
python3.11 -m unittest discover -s tests           # 664 OK
bash scripts/validate.sh                            # 13/13 OK

# Tests rev. 80 aislados
python3.11 -m unittest tests.test_rev80_cart_tool          # 12 OK
python3.11 -m unittest tests.test_rev80_llm_cascade        # 14 OK
python3.11 -m unittest tests.test_rev80_summary_from_db    # 5 OK

# Sanity conversational (single-turn no debería regresionar)
python3.11 scripts/uat/rev79_conversation_scenarios.py --only 1 7
# → 2 PASS · 0 FAIL · 0 SKIP
```

---

## Riesgos residuales

- **R1 (mitigado)**: cart populate-on-demand puede sumar items duplicados
  si el resolver los encuentra dos veces en turnos consecutivos.
  **Mitigación actual**: solo se popula cuando el cart está vacío.
  **Pendiente**: idempotencia más fina (compare-and-swap por content hash).

- **R2**: la cascada LLM aún no está cableada en el path principal — los
  503 sostenidos siguen llegando al worker tal cual. Ganancia plena
  llega al cablearlo en rev. 81.

- **R3**: `compute_shipping_inputs` asume que `product_variations.weight_kg`
  está poblado. Pre-flight confirmó 0 NULL en el tenant productivo, pero
  para tenants nuevos sin datos completos el fallback de
  `shipping_quote_tool` actual sigue siendo necesario.
