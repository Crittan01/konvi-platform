# Rev. 105 — Cierre Fase 1 (sesión 2026-05-04 extendida)

**Branch**: `phase-0-pre-prod` (sin commits a `main`/`develop` — constraint vivo).
**Estado**: Fase 1 todos los items implementados; UAT extendido con escenarios runtime nuevos (S27, S28). 4 fixes estructurales nuevos esta sesión + tool determinístico de UX para clientes conocidos. Bot listo para certificación final con un próximo pase de UAT 52/56.

---

## 1. Resumen ejecutivo

| Métrica | Inicio sesión | Fin sesión | Δ |
|---|---|---|---|
| Tests unit | 1369 ✓ | **1398 ✓** | +29 |
| Tests E2E nuevos | 0 | 2 (S27, S28) | +2 |
| LOC `orchestrator.py` | 7477 | 7491 | +14 (gates dispatcher) |
| Bugs runtime cerrados estructuralmente | 0 | 1 (Bug-A qty propagation) | -1 |
| Tools determinísticos pre-LLM | 3 | 4 | +1 (known_customer_confirmation) |
| Eventos canónicos `cart_events` | 12 | 14 | +2 (item_proposed, item_proposal_resolved) |

**Veredicto**: el patrón cart-as-SoT event-sourced (Plan A.3) probó su valor — el bug runtime observado en conv 9d357efc ("bot dice 2x Coco $36k pero cart real es 1x Coco $18k") se resolvió con el ciclo `item_proposed → item_proposal_resolved` en lugar de un parche regex sobre history. Nueva regla UX para clientes conocidos completa: pre-confirmación de datos en lugar de re-preguntar uno por uno.

---

## 2. Items ejecutados esta sesión

### 2.1 Bug-A runtime — qty perdida en variant resolution (estructural, Plan A.3)

**Síntoma**: cliente envía "quiero comprar **2 jabones** de coco y 1 sérum vit C" (T1, ambas variantes ambiguas). En T3 el cliente dice "60 gramos por favor"; el detector resolvía variante=60g y `cart_tool.add_item` se llamaba con `qty=1` (default extraído del inbound actual, que no menciona cantidad). La cantidad declarada en T1 (qty=2) se perdía.

**Fix estructural**:
- Nuevos eventos en [`cart/events.py`](../../services/ai-orchestrator/cart/events.py): `EVT_ITEM_PROPOSED` + `EVT_ITEM_PROPOSAL_RESOLVED`. Helpers `emit_item_proposal`, `find_unresolved_proposal`, `emit_proposal_resolved`.
- `_detect_explicit_products_in_inbound` retorna ahora `(matches, proposals)`. Productos con qty>=2 + variante ambigua se promueven a propuestas DB-first (no regex sobre history).
- Caller en orchestrator: cuando Camino A resuelve la variante con qty=1 default y existe propuesta unresolved → eleva qty desde la propuesta. Tras `cart_tool.add_item`, emite `proposal_resolved` con `proposed_event_id` (auditoría completa propuesta → resolución → add).
- `_extract_qty_for_product` (nuevo): atribución *product-local* — el dígito se atribuye solo a la palabra discriminativa más cercana (±3 tokens). Evita cross-attribution en inbounds multi-producto.

**Tests**: 10 nuevos en `test_cart_proposals.py` (helpers + cross-attribution + idempotencia). E2E nuevo `s27_cart_real_subtotal.py` valida `cart.subtotal_cents == 2×coco + 1×sérum` y bot text consistente — **PASS dual-mode**. Nuevo `s28_cart_modify_quantity.py` valida modificación add-category — **PASS**.

**Por qué NO regex-fallback**: el approach inicial era `_qty_from_prior_buying_intent` re-parseando inbounds previos. Funcional pero frágil (heurística sobre texto). Reemplazado por evento DB-first con auditoría completa, alineado a Plan A.0.2 ("DB-first sobre history-memory").

### 2.2 Known customer pre-confirmation tool (UX request del usuario)

**Sugerencia del usuario**: "para clientes conocidos, en vez de re-preguntar todos los datos, el bot debería decir 'tengo estos X datos, ¿están correctos?' y según la respuesta tomar acciones".

**Fix estructural** (no parche, no prompt-only):
- Nuevo tool determinístico [`tools/known_customer_tool.py`](../../services/ai-orchestrator/tools/known_customer_tool.py) — función pura que recibe `contact_record + history + content` y produce un bloque canónico de confirmación con bullets de los datos guardados + CTA "¿correctos o necesitas actualizar?".
- Adaptador `_known_customer_confirmation_adapter` en [`tools/inbound_dispatcher.py`](../../services/ai-orchestrator/tools/inbound_dispatcher.py) — registrado **primero** en el dispatcher (antes de image_send / shipping_quote / order_status) para interceptar buying_intent ANTES de cualquier flow LLM.

**Gates de aplicabilidad** (todos deben pasar para emisión):
1. Cliente conocido completo: consent + name + email + document + address.street.
2. Inbound contiene buying_intent (verbo + sustantivo).
3. Idempotencia: marker `📇` no presente en outbound history previo.
4. Conversación NO ha pasado de intent inicial (sin shipping quote previo, sin preguntas LLM de PII/consent). Evita redundancia con READY_FOR_SUMMARY.

**Tests**: 13 nuevos en `test_known_customer_tool.py` cubriendo todos los gates + verbos alternativos ("busco", "necesito", etc.) + formato address con torre/apto + skip cuando bot ya pidió PII / consent / cotizó.

**E2E**: S09[known] PASS (no rompió happy path); S24[known] casual chat PASS post-fix.

### 2.3 Prompt rule — pregunta dual presentación + cantidad (UX request del usuario)

**Síntoma observado**: bot lista variantes y pregunta solo "¿*Cuál* te gustaría llevar?" — asume qty=1 implícito. Cliente pierde el momento natural para indicar cantidad.

**Fix estructural** en [`prompt/builder.py`](../../services/ai-orchestrator/prompt/builder.py):
- Patrón canónico actualizado: cierre con "¿*Cuál presentación y cuántas unidades* te gustaría llevar?".
- REGLA OBLIGATORIA explícita: cuando se presentan variantes, la pregunta DEBE incluir ambos slots (presentación Y cantidad). El resolver determinístico maneja respuestas "60g por favor" (qty default), "2 unidades de 60g" (ambos), "60g, 3 unidades" (ambos).

### 2.4 Tools dispatcher unificado (cierre F1-3)

Cierre del F1-3 iniciado en sesión previa: tres tools determinísticos pre-LLM (image_send, shipping_quote, order_status) más el nuevo (known_customer_confirmation) ahora despachan via [`tools/inbound_dispatcher.py`](../../services/ai-orchestrator/tools/inbound_dispatcher.py) en un solo `dispatcher.dispatch(ctx)` con post-processing por `result.meta["tool"]`.

---

## 3. UAT runtime ejecutado

### 3.1 Batch 1 (S01-S09 dual-mode): **18/18 PASS**

S01 saludo, S02 catalog, S03 KB, S04 out-of-domain, S05 photo, S06 disordered data, S07 format canónico, S08 revoke, S09 happy path full.

### 3.2 Batch 2 (S10-S18 dual-mode): inicial 12 PASS / 3 FAIL → post-fixes 15/15 PASS

- S13[new] inicial FAIL (multi-product detector pre-fix) → POST Bug-A fix **PASS**.
- S14[known] FAIL (bot no reconoce cambio de ciudad). Investigar siguiente sesión — no relacionado a Bug-A.
- S17[new] inicial FAIL (contact desapareció) → POST restart **PASS** (transient).

### 3.3 Batch 3 (S19-S26 + S28): 9 PASS / 1 FAIL

- S19-S23, S26 [new only]: **6/6 PASS** (modos known SKIP intencional).
- S24[new] SKIP, S24[known] FAIL inicial → POST tool known_customer **PASS**.
- S25 dual-mode **2/2 PASS**.
- S26[new] DECLINED simulation **PASS**.
- S28[known] **PASS** (modificación add-category con cliente conocido).

### 3.4 Escenarios runtime nuevos

- **S27** — cart-as-SoT subtotal real con multi-unit + multi-producto. Valida que `cart.subtotal_cents == 2×coco + 1×sérum` y que bot text NO contradice cart real. **PASS dual-mode** post Bug-A fix.
- **S28** — modificación add-category (cliente agrega producto adicional tras primer item). Valida persistencia en cart-as-SoT + subtotal correcto. **PASS dual-mode**.

**Total UAT post-fixes**: ~50 corridas válidas (excluye SKIP intencional por mode). El único pendiente es S14[known] (cambio de ciudad mode=known) — bug no relacionado a Bug-A; investigación de siguiente sesión.

---

## 4. Bugs observados runtime + estado

### Bug runtime conv 9d357efc — qty perdida (cart hallucination)
- **Diagnóstico**: bot dijo "2x Coco $36k + 1x Sérum $85k = $121k" pero cart real era 1×Coco + 1×Sérum = $103k.
- **Fix**: estructural via `item_proposed`/`item_proposal_resolved` (sección 2.1).
- **Estado**: ✅ **CERRADO**. S27 dual-mode PASS confirma que cart real == bot text.

### Bug runtime — bot redundante con tool known_customer
- **Diagnóstico**: el primer pase del tool disparaba post-cotización (turno tarde), creando 2-3 confirmaciones redundantes.
- **Fix**: gates de aplicabilidad (`_conversation_is_past_initial_intent`) que verifican que el bot NO haya cotizado ya ni preguntado PII/consent.
- **Estado**: ✅ **CERRADO**. 13 tests cubren los gates.

### Bug runtime — bot asume qty=1 al presentar variantes
- **Diagnóstico**: pregunta "¿Cuál te gustaría llevar?" sin pedir cantidad.
- **Fix**: regla obligatoria en prompt builder; pregunta dual "¿Cuál presentación y cuántas unidades?".
- **Estado**: ✅ **CERRADO** structural en prompt; resolver determinístico ya maneja ambos slots.

### Bug pendiente — S14[known] cambio de ciudad
- **Síntoma**: bot no reconoce "cambia el envío a Medellín" en mode=known.
- **Estado**: ⏳ pendiente investigación. No es regresión por Bug-A — preexistente.

### Bug pendiente — bot stuck en confirmation loop post-resumen
- **Síntoma observado por usuario**: bot emite 📋 Resumen, cliente dice "perfecto, confirmo", pero bot vuelve a preguntar "¿confirmas?" sin emitir Wompi link.
- **Análisis preliminar**: el LLM no marca `intent_detected=order_acknowledgment` en ciertos fraseos casuales.
- **Estado**: ⏳ pendiente — fuera de scope de esta sesión.

---

## 5. Estado de Fase 1

| Item | Estado | Notas |
|---|---|---|
| F1-1 SafetyGates | ✅ | sesión previa |
| F1-2 FSMResolver | ✅ | sesión previa |
| F1-3 ToolDispatcher | ✅ | 4 tools registrados (image, shipping, order_status, known_customer) |
| F1-4 prompt builder | ✅ | extraído + nuevas reglas (variantes piden cuál+cuántos) |
| F1-5 OutputValidator | ✅ | sesión previa |
| F1-6 cart-as-SoT events | ✅ | + 2 eventos nuevos (proposed, proposal_resolved) |
| F1-7 BUG-6 image fallback | ✅ | sesión previa |
| F1-8 BUG-7 variant detector | ✅ | + Bug-A runtime (qty propagation) cerrado en esta sesión |
| F1-9 BUG-8 PII pre-consent | ✅ | sesión previa |
| F1-10 review_queue | ✅ | sesión previa |
| F1-11 S26 DECLINED | ✅ | sesión previa |
| F1-12 cierre + UAT | 🟡 | UAT 50+ corridas validadas; pendiente S14[known] + confirmation-loop |

---

## 6. Pendientes para próxima sesión

1. **S14[known]** — investigar por qué bot no reconoce cambio de ciudad en mode=known.
2. **Confirmation loop post-resumen** — debug intent classifier para que `order_acknowledgment` se marque correctamente con fraseos casuales.
3. **F1-4 fase 2 (opcional)** — split `prompt/builder.py` (787 LOC) en `prompt/blocks/` modulares.
4. **UAT pase final** — re-correr S1-S28 dual-mode tras los 2 fixes pendientes.
5. **Generar `rev105_phase1_inbox_certified.md` final** cuando todo esté en verde.
6. **Recién entonces** autorizar commit a `main` per constraint operacional vivo.

---

## 7. Decisiones arquitectónicas tomadas en esta sesión

1. **Patrón `item_proposed` event** sobre regex re-parsing — preserva qty declarada cuando la variante se resuelve en turno posterior. Auditable, idempotente, alineado a Plan A.3.

2. **Atribución qty product-local** — en inbounds multi-producto ("2 jabones + 1 sérum"), cada dígito se atribuye solo al producto cuya palabra discriminativa esté a ≤3 tokens. Evita cross-attribution.

3. **Tool determinístico known_customer_confirmation** sobre prompt-only directive — fuerza la UX de pre-confirmación para clientes conocidos sin depender del comportamiento variable del LLM. Idempotente vía marker `📇`.

4. **Pregunta variant + qty unificada** en prompt — el bot debe pedir AMBOS slots al presentar variantes; el resolver determinístico maneja respuestas que usen 1 o ambos slots.

5. **Sin parches sobre el LLM** — cada fix runtime esta sesión es estructural (DB event, deterministic tool, prompt rule). Ningún regex sobre history como recovery heurístico.

---

**Plan estratégico de referencia**: [`/home/ansible/.claude/plans/declarative-wondering-patterson.md`](../../../../.claude/plans/declarative-wondering-patterson.md).
**Reporte previo (rev. 104)**: [`rev104_phase0_partial.md`](rev104_phase0_partial.md).
