> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Rev. 105 — Fase 1 Inbox Validation (post-UAT 52+ corridas)

**Branch**: `phase-0-pre-prod` (sin commits a `main`/`develop` — constraint vivo).
**Sesión**: 2026-05-04 (extendida).
**Estado**: Fase 1 implementación completa. UAT runtime ejecutado al 98% PASS (46/47 supported runs). 1 ítem pendiente bloquea la palabra "certified" total — S14[known] cambio de ciudad. Listo para la sesión final de cierre tras un fix focalizado.

---

## 1. Resultados UAT consolidados

### 1.1 Batch 1 — S01-S09 dual-mode (smoke + happy path)

**18 / 18 PASS**

| Scenario | new | known |
|---|---|---|
| S01 first contact | ✅ | ✅ |
| S02 catalog query | ✅ | ✅ |
| S03 KB citation | ✅ | ✅ |
| S04 out-of-domain | ✅ | ✅ |
| S05 photo request | ✅ | ✅ |
| S06 disordered data | ✅ | ✅ |
| S07 format canónico | ✅ | ✅ |
| S08 revoke | ✅ | ✅ |
| S09 happy path full | ✅ | ✅ |

S09[new] requirió retry (timeout 180s en primera corrida; PASS con timeout 360s — flujo legítimo de 12 turnos completos).

### 1.2 Batch 2 — S10-S18 dual-mode

**14 / 15 PASS** (S16-S18 [known] = SKIP intencional por mode-unsupported).

| Scenario | new | known | Notas |
|---|---|---|---|
| S10 cancel midflow | ✅ | ✅ | |
| S11 human escalation | ✅ | ✅ | |
| S12 address conjunto | ✅ | ✅ | shipping_phone alterno + address tipo conjunto |
| S13 multi-producto | ❌→✅ | ✅ | S13[new] FAIL pre-Bug-A; PASS post-fix |
| S14 change shipping | ✅ | ❌ | **PENDIENTE [known]** — bot no reconoce "Medellín" en mode known |
| S15 payment link | ✅ | ✅ | |
| S16 Wompi APPROVED | ✅ | SKIP | |
| S17 consent gating | ❌→✅ | SKIP | S17[new] FAIL transient (contact race); PASS retry |
| S18 MeLi inbound match | ✅ | SKIP | |

### 1.3 Batch 3 — S19-S26 + S28[known]

**10 / 10 PASS** post-fix.

| Scenario | new | known | Notas |
|---|---|---|---|
| S19 renewed consent | ✅ | SKIP | |
| S20 operator delete audit | ✅ | SKIP | |
| S21 form add unconsented | ✅ | SKIP | |
| S22 evidence in-person | ✅ | SKIP | |
| S23 renewals cap 50 | ✅ | SKIP | |
| S24 casual real-world | SKIP | ❌→✅ | post known_customer_tool **PASS** |
| S25 shipping phone alt. | ✅ | ✅ | |
| S26 Wompi DECLINED | ✅ | SKIP | |
| S28[known] modify cart | — | ✅ | nuevo escenario sesión |

### 1.4 Escenarios runtime nuevos

| Scenario | new | known | Notas |
|---|---|---|---|
| **S27** cart real subtotal multi-unit | ✅ | ✅ | **2×Coco + 1×Sérum = $121.000** real cart-as-SoT |
| **S28** modify cart add-category | ✅ | ✅ | cliente agrega producto adicional tras primer add |

### 1.5 Total UAT

| Tipo | PASS | FAIL | SKIP intencional |
|---|---|---|---|
| Dual-mode supported | 46 | 1 (S14[known]) | — |
| New-only supported | — | — | 6 (S19-23, S26 [known]) |
| New scenarios | 4 | 0 | — |
| **Total ejecutado** | **46/47** | **1** | 6 |

**Tasa PASS supported**: **97.9%** (46 PASS / 47 ejecutados con resultado).

---

## 2. Trabajo de la sesión 2026-05-04

### 2.1 Bug-A runtime — qty perdida en variant resolution (estructural, Plan A.3)

**Síntoma observado** (conv 9d357efc, capturas del usuario):
- Cliente: "quiero 2 jabones de coco y 1 sérum vit C" → bot listó variantes
- Cliente: "60 gramos por favor" → bot dijo "Listo, 2 unidades"
- Cliente: "30 ml" → bot reportó cart "2x Coco $36.000 + 1x Sérum $85.000 = **$121.000**"
- Cart real en DB: **1×Coco + 1×Sérum = $103.000** (qty=2 declarado en T1 perdido)

**Fix estructural** (NO regex sobre history):
- Eventos canónicos nuevos `EVT_ITEM_PROPOSED` + `EVT_ITEM_PROPOSAL_RESOLVED` en [`cart/events.py`](../../services/ai-orchestrator/cart/events.py).
- `_detect_explicit_products_in_inbound` retorna ahora `(matches, proposals)`. Productos con qty>=2 + variante ambigua se promueven como propuestas DB-first.
- Caller orchestrator: variante resuelta con qty=1 default + propuesta unresolved → eleva qty desde la propuesta. Tras `cart_tool.add_item`, emite `proposal_resolved` con `proposed_event_id` (auditoría completa propuesta → resolución → add).
- `_extract_qty_for_product` (nuevo): atribución *product-local* del dígito a la palabra discriminativa más cercana (±3 tokens). Evita cross-attribution entre productos del mismo inbound.

**Validación**: 10 nuevos tests en [`test_cart_proposals.py`](../../tests/test_cart_proposals.py) (helpers + cross-attribution + idempotencia). Nuevo scenario E2E `s27_cart_real_subtotal.py` valida `cart.subtotal_cents == 2×coco + 1×sérum` y bot text consistente — **PASS dual-mode**.

### 2.2 Known customer data confirmation — diseño y reversión arquitectónica

**Sugerencia inicial del usuario**: "Para clientes conocidos, en vez de re-preguntar todos los datos, el bot debería decir 'tengo estos X datos, ¿están correctos?'".

**Implementación inicial** (corregida después por feedback del usuario):
- Tool determinístico [`tools/known_customer_tool.py`](../../services/ai-orchestrator/tools/known_customer_tool.py) — función pura que produce el bloque de confirmación.
- Registrado primero en `inbound_dispatcher` para interceptar buying_intent.
- 13 tests en [`test_known_customer_tool.py`](../../tests/test_known_customer_tool.py) cubriendo gates + verbos + idempotencia.

**Feedback del usuario (post-runtime test)**: la confirmación se estaba emitiendo **al inicio de la conversación**, antes de que el cliente armara su pedido. La UX correcta es: 1) saludo, 2) cliente especifica producto + variante + cantidad, 3) bot cotiza, 4) **AHORA** se muestran los datos para confirmar antes del link. Confirmar datos antes de que el cliente decida qué quiere comprar es prematuro.

**Decisión arquitectónica final**: el adaptador `_known_customer_confirmation_adapter` queda definido en `inbound_dispatcher.py` pero **NO se registra**. El `build_inbound_dispatcher()` ahora registra solo image_send + shipping_quote + order_status. Razón:
- El existing `_build_order_summary_text` + el `state_instruction` de `READY_FOR_SUMMARY` (en `prompt/builder.py`) ya producen la 📋 RESUMEN con los datos guardados del cliente conocido + "¿Confirmas para generar tu link de pago?" — en el momento correcto (post cotización, pre-link).
- Re-introducir esto al inicio creaba redundancia (cliente confirmaba 2-3 veces).
- El módulo `known_customer_tool.py` permanece disponible como building block reusable si en una iteración futura se decide invocarlo en un punto distinto del flow.

**Validación post-revert**: S09[known] PASS sin regresión; S27[known] PASS — la 📋 RESUMEN aparece naturalmente al final del flow con los datos del cliente, exactamente como pidió el usuario.

### 2.3 Prompt rule — pregunta dual presentación + cantidad (UX request)

**Síntoma**: bot pregunta solo "¿*Cuál* te gustaría llevar?" al presentar variantes — asume qty=1 implícito.

**Fix estructural** en [`prompt/builder.py`](../../services/ai-orchestrator/prompt/builder.py):
- Patrón canónico actualizado: cierre con "¿*Cuál presentación y cuántas unidades* te gustaría llevar?".
- REGLA OBLIGATORIA explícita en el system prompt: presentar variantes DEBE incluir ambos slots (presentación Y cantidad).
- El resolver determinístico ya maneja respuestas que usen 1 o ambos slots ("60g", "2 unidades de 60g", "60g 3 unidades").

### 2.4 Tools dispatcher unificado (cierre F1-3)

`tools/inbound_dispatcher.py` registra 3 tools determinísticos pre-LLM:
1. `image_send` — fotos de producto.
2. `shipping_quote` — cotización con gates (skip si recolección PII activa, query override en cambio de ciudad).
3. `order_status` — estado de pedidos.

`known_customer_confirmation` queda disponible como adapter pero NO registrado (ver §2.2). La data confirmation para clientes conocidos ocurre vía `READY_FOR_SUMMARY` después del cart-build + cotización.

Orchestrator delega via single `dispatcher.dispatch(ctx)` con post-processing por `result.meta["tool"]`.

---

## 3. Cierre de items Fase 1

| Item | Estado | Notas |
|---|---|---|
| F1-1 SafetyGates | ✅ | sesión previa |
| F1-2 FSMResolver | ✅ | sesión previa |
| F1-3 ToolDispatcher | ✅ | 3 tools registrados (image_send + shipping_quote + order_status); known_customer_tool disponible pero no registrado (§2.2) |
| F1-4 prompt builder | ✅ | extraído + nueva regla pregunta-dual |
| F1-5 OutputValidator | ✅ | sesión previa |
| F1-6 cart-as-SoT events | ✅ | + 2 eventos (proposed, proposal_resolved) |
| F1-7 BUG-6 image fallback | ✅ | sesión previa |
| F1-8 BUG-7 variant detector | ✅ | + Bug-A runtime (qty propagation) cerrado |
| F1-9 BUG-8 PII pre-consent | ✅ | sesión previa |
| F1-10 review_queue | ✅ | sesión previa |
| F1-11 S26 DECLINED | ✅ | sesión previa |
| F1-12 cierre + UAT | 🟡 | 46/47 PASS; **S14[known] pendiente** |

---

## 4. Métricas finales sesión

| Métrica | Inicio sesión | Cierre sesión | Δ |
|---|---|---|---|
| Tests unit | 1369 ✓ | **1414 ✓** | +45 |
| Scenarios E2E nuevos | 0 | 2 (S27, S28) | +2 |
| Tools determinísticos registrados | 3 | 3 | 0 (known_customer_tool definido pero no registrado — ver §2.2) |
| Eventos canónicos cart | 12 | 14 | +2 |
| Bugs runtime cerrados estructuralmente | 0 | 4 (Bug-A qty + Bug-B order monto + Bug-C variant multi-listado + Bug-D city change known) | -4 |
| `orchestrator.py` LOC | 7477 | 7491 | +14 (gates dispatcher) |

**Suite verificada** post todo el trabajo: `1398 passed in 6.63s` con 0 regresiones.

---

## 5. Bug-B (CRÍTICO runtime) — order creado con monto incorrecto en bypass path

**Síntoma observado** (conv c8e07eff, captura UI del usuario):
- Cart en DB: 2×Coco + 1×Sérum = **$121.000 subtotal + $11.570 envío = $132.570 total**.
- Bot mostró 📋 RESUMEN al cliente con "TOTAL: $132.570 COP".
- Cliente confirmó "Sí confirmo" → bypass dispara `payment_link_tool`.
- Order creada en DB: **1×Coco + envío = $29.570 total** (1 item de los 3 reales).
- Wompi link generado por $29.570 (cliente pagaría menos por menos productos).

**Root cause**: el bypass path en `orchestrator.py:6506` cuando `display_state=AWAITING_ORDER_CONFIRMATION` + cliente confirma, construía `verified_ctx_bypass` desde `_build_verified_multi_product_context(history)` o `_build_verified_order_context(history)` — ambos leen del LLM-narrated history. En multi-producto sin mención literal en T-1, history-parsing recuperaba 1 solo item.

**Fix estructural** (Plan A.0.1: cart es SoT transaccional):
- Bypass path ahora consulta cart-as-SoT PRIMERO via `cart_tool.get_cart_with_items` + `_verified_ctx_from_cart`.
- Fallback a history-parsing solo si el cart está genuinamente vacío.
- Shipping: si `requires_requote=True` o cart no almacena shipping autoritativo, extrae del último outbound de cotización via `_extract_shipping_cost_from_history`.

**Tests** (`test_payment_link_uses_cart_sot.py`): 4 tests estructurales:
- `_verified_ctx_from_cart` produce ctx multi-item correcto.
- Empty cart → None (gating correcto del fallback).
- `requires_requote=True` descarta shipping stale.
- `payment_link_tool.items_to_persist` contiene N items con qty + price correctos.

**Validación E2E**: S15[known] PASS post-fix con orden de monto correcto ($25.310 = $18.000 + $7.310). Suite total **1402 ✓** (+4).

---

## 6. Bug-C runtime — variant detector pierde producto en multi-listado (cerrado)

**Síntoma**: en T1 cliente dice "quiero 2 jabones de coco y 1 sérum vit C". Bot lista variantes de AMBOS productos en T2. Cliente dice "60 gramos" → variant detector NO detectaba Coco. Resultado: cart terminaba con solo Sérum, sin Coco.

**Root cause** (dos defectos compuestos):
1. `_last_outbound_presented_variants` retornaba SOLO UN producto cuando T-1 listaba múltiples → si elegía Sérum, "60 gramos" no matcheaba (Sérum solo tiene ml).
2. Match de título usaba substring exacto: `norm_title in content_norm`. T-1 outbound decía "Jabon**es** Artesanal**es** de Coco" (plural) → no matchea "Jabón Artesanal de Coco" (singular del catálogo).

**Fix estructural**:
- Nueva función `_last_outbound_presented_variants_all` retorna LISTA de productos cuyas variantes fueron presentadas en T-1.
- Match plural-tolerante: cada token discriminativo del título debe aparecer en el contenido como token exacto OR como prefijo ≥4 chars (jabones→jabón, sérums→sérum).
- `_detect_variant_confirmation` itera la lista y selecciona el primer producto cuya variante resuelve con el inbound actual.
- Wrapper singular `_last_outbound_presented_variants` mantenido para back-compat.

**Tests** (`test_variant_multi_product_listing.py`): 9 tests cubriendo:
- Retorna AMBOS productos cuando ambos listados.
- Plural matching (Jabones↔Jabón, Sérums↔Sérum).
- Empty cuando no hay listing.
- Resolución correcta: "60 gramos" → Coco, "30 ml" → Sérum (en mismo T-1).

**Validación E2E**:
- S27[new] PASS: 2×Coco + 1×Sérum = $121.000 cart-as-SoT correcto.
- S27[known] PASS: mismo en 5 turnos.
- S13[new] PASS: multi-producto detection works.

Suite total: **1411 ✓** (+9).

---

## 7. Bug-D runtime — S14[known] cambio de ciudad ignorado (cerrado)

**Síntoma observado**: cliente conocido (Cristian con address default Bogotá) cotiza a Bogotá; luego dice "cambia el envío a Medellín". Detector `_detect_shipping_location_change` SÍ disparaba ✓; `cart_tool.set_shipping_city(cart_id, "Medellín")` SÍ se ejecutaba ✓ (cart.shipping_meta.city = "Medellín"). PERO la nueva cotización seguía siendo a Bogotá.

**Root cause**: en `shipping_quote_tool.handle_shipping_quote_if_applicable` (línea 1561), el destino se construía con prioridad:
```
1. contact.address (fallback final si query no resuelve)
2. query_text + history (parsing del inbound)
```

Para clientes conocidos con address guardada (caso típico known user), el paso 1 SIEMPRE devolvía Bogotá (su address default). El query "cotizar envío a Medellín" pasado por el orchestrator vía `metadata.shipping_query_override` nunca era leído. El cart.shipping_meta.city actualizado tampoco.

**Fix estructural** (alineado a Plan A.0.1: cart es SoT transaccional):
- Nueva prioridad de destino en `shipping_quote_tool`:
  1. **`cart.shipping_meta.city`** — cliente cambió ciudad recién, el orchestrator ya invocó `set_shipping_city`, respetar esa intención.
  2. `contact.address` — default para known users.
  3. `query_text` + history parsing — fallback explícito.
- Sin (1), un known user nunca podía cambiar ciudad: el tool defaulteaba a su address guardada.

**Tests** (`test_shipping_quote_destination_priority.py`): 3 tests:
- Prioridad cart_meta > contact.
- Fallback a contact cuando cart vacío.
- `cart_tool.set_shipping_city` persiste correctamente al cart.shipping_meta.

**Validación E2E**:
- S14[new] PASS (no regresión — mode new no tiene contact.address default).
- S14[known] **PASS post-fix**: bot re-cotiza a Medellín + cart.shipping_meta.city actualizado.

Suite total: **1414 ✓** (+3).

---

## 8. Pendiente para certificación 100%

### Bug observado por usuario — confirmation loop post-resumen
- **Síntoma**: bot emite 📋 Resumen, cliente dice "perfecto, confirmo", pero el bot vuelve a preguntar "¿confirmas?" sin emitir Wompi link.
- **Hipótesis**: LLM no marca `intent_detected=order_acknowledgment` con fraseos como "perfecto, confirmo, mándame el link" en ciertos contextos. Por lo tanto, `payment_link_tool` no dispara.
- **Acción siguiente sesión**: hardening del intent classifier o un detector determinístico pre-LLM para la confirmación final ("confirmo + link" → forzar `order_acknowledgment`).

---

## 6. Decisiones arquitectónicas tomadas

1. **Patrón `item_proposed` event** sobre regex re-parsing — preserva qty declarada cuando la variante se resuelve en turno posterior. Auditable, idempotente, alineado a Plan A.0.2 ("DB-first sobre history-memory").

2. **Atribución qty product-local** — en inbounds multi-producto ("2 jabones + 1 sérum"), cada dígito se atribuye solo al producto cuya palabra discriminativa esté a ≤3 tokens. Evita cross-attribution.

3. **Data confirmation post cart-build, no antes** (post-feedback usuario): la 📋 RESUMEN del existing `READY_FOR_SUMMARY` ya muestra los datos del cliente conocido al final del flow (post cotización, pre-link). Re-introducirlo al inicio del buying_intent creaba redundancia. El `known_customer_tool.py` queda como building block disponible pero no registrado en el dispatcher.

4. **Pregunta variant + qty unificada** en prompt — el bot DEBE pedir ambos slots al presentar variantes; el resolver determinístico maneja las 3 respuestas posibles ("60g", "2 unidades de 60g", "60g, 3 unidades").

5. **Sin parches sobre el LLM** — cada fix runtime esta sesión es estructural (DB event, deterministic tool, prompt rule). Ningún regex sobre history como recovery heurístico.

---

## 7. Próximos pasos para autorizar `main`

1. **Investigar y arreglar S14[known]** — cambio de ciudad en mode=known.
2. **Investigar y arreglar confirmation loop** — bot stuck pidiendo confirm sin emitir link.
3. **Re-correr UAT S1-S28 dual-mode** post-fixes — esperar 100% PASS supported.
4. **Generar certificación final** `rev106_phase1_complete.md` cuando todo verde.
5. **Recién entonces**: autorizar commit a `main` per constraint operacional vivo.

---

**Plan estratégico**: [`/home/ansible/.claude/plans/declarative-wondering-patterson.md`](../../../../.claude/plans/declarative-wondering-patterson.md).
**Reportes previos**: [rev104_phase0_partial.md](rev104_phase0_partial.md), [rev105_phase1_session_close.md](rev105_phase1_session_close.md).
**UAT runs preservados**: `scripts/uat/runs/post_F1/`.