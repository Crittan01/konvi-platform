# ADR-0039 — BLOQUE K-2: Retiro del pipeline V1 (orchestrator legacy)

- **Estado**: Aceptado
- **Fecha**: 2026-07-12
- **Contexto de iniciativa**: Production-readiness (Prompt Maestro), BLOQUE K (consolidación / saneamiento de código). Continúa la decisión founder **J-4 #4** (retirar V1 tras verificar prod).

## Contexto

El Orchestrator arrastraba **dos pipelines conversacionales coexistiendo**:

1. **V1 (legacy monolítico)** — `build_and_run_orchestration()` en `orchestrator.py`
   (~3.688 LOC) + un builder de system prompt en `prompt/builder.py` (876 LOC) +
   ~88 helpers heurísticos deterministas (TIER2 category-lock, `variant_confirmation`,
   `explicit_products_in_inbound`, detección de intención por regex, etc.) + el
   conductor de checkout `checkout_form.py` (350 LOC) + un shadow harness de
   migración en `agentic/dispatcher.py`.
2. **V3 (agentic)** — `agentic/` (loop LLM con tools, invariants deterministas,
   FSM resolver). Es el **único path productivo** desde el cutover (Fase C, ADR-0018).

El dispatcher enrutaba a V1 **solo** en el `else` de `if agentic_enabled`. Verificación
en prod: **1 tenant (KAIU), agentic-enabled, 0 tenants en V1**. `agentic_enabled` vive
en `tenant_integrations.meta` (provider='agentic', default `False` si no existe el row).

V1 era, por tanto, **código muerto en producción** — pero seguía en el árbol, con sus
heurísticas no-determinísticas (las que el propio dispatcher documentaba como capaces de
"alucinar items inexistentes") y ~40 archivos de test dedicados. Deuda de mantenimiento,
superficie de confusión y ruido de cobertura.

## Decisión

**Retirar V1 en su totalidad.** El agentic es la única fuente de verdad. Un tenant que
llegue al path no-agentic (misconfiguración de provisioning; 0 en prod) recibe
**degraded + escalation a operador humano** — interpretación segura, consistente con el
path de crash del agentic y con la decisión J-4 #3 (`fsm_states_denied → escalar`).

### Alcance eliminado (verificado determinísticamente)

| Elemento | LOC |
|---|---|
| `orchestrator.py`: `build_and_run_orchestration` + `_build_system_prompt` + 88 helpers V1-only | ~7.794 |
| `prompt/builder.py` (+ paquete `prompt/` vacío) | 876 |
| `checkout_form.py` (`CheckoutFormConductor`, V1-only) | 350 |
| Shadow harness (`_run_agentic_shadow*`, flag `AGENTIC_SHADOW_ENABLED`) en dispatcher | ~124 |
| **Total código de producción** | **~9.140** |
| Tests V1 borrados | 36 archivos |
| Tests mixtos editados (se preserva cobertura viva) | 6 archivos |
| Scripts UAT/e2e manuales del pipeline V1 (fuera del gate) | 3 |

### Método de verificación (por qué es seguro pese al tamaño)

El único cambio *alcanzable en runtime* es el route del dispatcher (~15 líneas). Todo lo
demás es deleción de código probado inalcanzable, verificada con:

1. **Call-graph AST determinístico** (fixpoint): una función es V1-only si TODOS sus
   callers de producción caen dentro de la región V1. Efecto de 2º orden incluido
   (helpers que solo llamaba `prompt/builder.py`).
2. **Dangling-ref proof import-aware**: 0 referencias reales a símbolos borrados en
   código vivo (descartó falsos positivos por colisión de nombres entre servicios, p.ej.
   el `_build_system_prompt` local de `services/api/routers/ai_preview.py`).
3. **Import + `compile()`** de `orchestrator` y `agentic.dispatcher` (cazó una
   referencia-como-valor a nivel de módulo — `_CHECKOUT_FORM_CONDUCTOR` — que el
   call-graph por-paréntesis no ve).
4. **Suite completa verde** (3.094 tests) + revisión adversarial.

### Comportamiento preservado

Las conductas V1 que importan **ya vivían en el agentic** y conservan cobertura:

- Cascade LLM (Gemini→Claude): `agentic/agent.py` vía `generate_with_cascade`.
- Human takeover / skip por status: gate del dispatcher (`status ∈ {human_takeover, closed}`).
- Habeas Data (consent revoke / SAR): `_handle_data_rights_if_intent` + `soft_revoke_consent`
  (agentic) y `data_subject_request.py` (API, `notify_sar_received`).
- Audit de turnos (`agentic_shadow_log`, `mode='cutover'`): `_persist_turn_audit()`
  (conservado — lo usa el path full).

## Consecuencias

**Positivas**
- `orchestrator.py`: 10.419 → ~2.625 LOC. Se elimina la ambigüedad de "dos builders".
- Desaparecen las heurísticas no-determinísticas señaladas como fuente de alucinación.
- Menos superficie de test/mantenimiento; el score del core del BOT sube.

**Neutrales / follow-up**
- `fsm/state_renderers.py` (V1-only: `render_needs_shipping_city`,
  `render_awaiting_carrier_selection`, `_format_price_cop`) quedó huérfano y **se
  eliminó en este mismo PR (commit K-2b)** tras verificar 0 importadores vivos (el
  agentic renderiza vía `agentic/system_prompt.py`). El test `test_cop_format_consolidation`
  se editó para conservar la cobertura viva de los formatters agentic.
- `_extract_first_name` sigue VIVO (lo usa `tools/payment_link_tool.py`) → se conserva.
  `_missing_address_fields` queda como re-export test-only en orchestrator (F401-exempt).
- La regla de UX "listado de catálogo amplio" era V1-only y NO está en el prompt agentic.
  No es regresión (0 tenants en V1), pero es una posible mejora del prompt agentic a
  evaluar por separado.

**Riesgos**
- Un tenant provisionado sin `agentic_enabled=true` recibiría degraded+escalation en vez
  de bot. Mitigado: el route loguea ERROR (visible en Sentry) para corregir provisioning;
  0 tenants en ese estado hoy.

## Relación

- Deriva de ADR-0018 (strangler-fig legacy→agentic) y de la decisión founder J-4.
- No requiere migración de DB (deleción de código puro).
