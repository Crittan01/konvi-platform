# Bugs Sem 7 F2 cierre — historial completo

**Estado al cierre de sesión 2026-05-19 ~16:30 UTC.**

Documento histórico de los 4 bugs descubiertos en UAT manual del founder
durante la sesión Sem 7 F2 cierre. **Todos arreglados arquitectónicamente
sin parches**. Validados end-to-end en runtime real del founder.

---

## ✅ Bug A — Multi-variant input ("1 de 100ml y 1 de 250ml") — RESUELTO

### Síntomas observados (pre-fix)

- Conv `a4db1801` (2026-05-19 ~01:25 UTC): cliente pidió 2 variantes del
  mismo producto → bot solo agregó 100ml, perdió 250ml.
- Conv `664ce6c1` (2026-05-19 ~02:05 UTC): mismo bug post primer fix
  inicial.

### Root cause (descubierto en 2 capas)

**Capa 1 — Detector de variantes**: `_resolve_variant_from_inbound`
tenía contrato "1 inbound → 1 variant", retornaba primer match y
terminaba sin evaluar restantes.

**Capa 2 — Caller en orchestrator**: dentro del `for _item in
_items_to_add:`, el primer add_item con `order_invalidated=True` hacía
emit resumen + **return** inmediato. Items restantes del loop nunca se
procesaban.

### Fix arquitectónico aplicado (commits 72abc3d + 4a35b4b)

**Capa 1**: `_resolve_variant_from_inbound` retorna `list[tuple[variant,
qty]]` (vacía, 1, o N). Detecta separadores (` y `, ` + `, `, `) y
segmenta el inbound. Helper nuevo `_match_single_variant_in_text`
extraído de la lógica original.

**Capa 2**: refactor del for loop para separar responsabilidades:
- Dentro del loop: SOLO persistir items + acumular `_invalidation_info`
  metadata. NO emitir outbound, NO return.
- Después del loop: si hubo invalidación acumulada, emitir UN solo
  resumen unificado leyendo cart FINAL con TODOS los items.

`_detect_variant_confirmation` también cambió contrato a `list[dict]`.
Caller updates: `_items_to_add = _variant_confirmed` (ya es lista).

### Validación runtime (conv e29d4c66, UAT manual founder)

Cart final post "1 de 100ml y 1 de 250ml" tras orden previa Jabón Coco:
```
* 1x Jabón Artesanal de Coco (60g): $18.000
* 1x Aceite de Almendras Dulces (100ml): $28.000
* 1x Aceite de Almendras Dulces (250ml): $52.000
Subtotal: $98.000 · Envío: $16.410 (recotizado) · TOTAL: $114.410
```

3 items distintos preservados + recotización lazy + link Wompi
generado #8EF6AB25.

### Tests

- 19 tests en `test_rev103_variant_confirmation.py` (18 adaptados al
  nuevo contrato + 1 nuevo `test_multi_variant_in_one_inbound`).
- 9 tests en `test_variant_multi_product_listing.py` (todos adaptados).
- 14 tests en `test_cart_proposals.py` (passing).

---

## ✅ Bug B — "Retomar carrito" no persistía items — RESUELTO

### Síntomas observados (pre-fix)

- Conv `17da4c7a` / `0a46350b` / `8a4ccb51`: cliente conocido pregunta
  "Tengo algo en carrito?" → bot detecta cart histórico + dice
  "Retomamos tu Jabón Coco" + arma resumen + crea orden + link Wompi.
  Cuando luego agrega Aceite, el Jabón Coco DESAPARECE del nuevo resumen.

### Root cause

`_persist_recovered_cart_items` (`orchestrator.py:972`) ya existe y hace
lo correcto (copiar items recuperados al cart de la conv actual). PERO
solo dispara si `_last_outbound_offered_cart_retake(history)` retorna
True. Los markers cubrían 11 frases ("carrito reciente", "tu carrito
anterior", etc.) pero NO las variantes fraseológicas que el LLM usaba:
- "carrito que se canceló"
- "retomarlo o prefieres ver otras opciones"
- "tenías un Jabón Artesanal..."

Sin matcher → items no persistían → cart real quedaba vacío → resumen
+ orden se construían via history-parsing (frágil, warning observable
`[BYPASS] cart vacío → fallback history-parsing (puede alucinar)`).
Subsiguiente add_item creaba cart NUEVO con solo el nuevo producto,
perdiendo el item original.

### Fix arquitectónico aplicado (commit 72abc3d)

Ampliar dominio del detector (NO parche, mismo patrón que Smells A/B
previos):
- 20+ markers ahora cubren todas las variantes del LLM:
  - "carrito que se cancel/abandon"
  - "te gustaría retomarlo/retomar"
  - "retomarlo o prefieres"
  - "tenías un/una"
  - "items en tu carrito" + plurales

### Validación runtime (conv e29d4c66)

"Sí retomarlo" → bot retomó Jabón Coco + items persistidos en cart real.
Subsiguiente add Aceite preservó Jabón Coco en resumen final.

---

## Cierre de sesión 2026-05-19

**Sesión rev. 106 acumulada (87+ commits en `phase-0-pre-prod`)**:

### Cerrado y validado end-to-end:
- Sem 7 F2 HSM templates (items 1-7) + ADR-0016
- Tenant-centric branding (segregación Konvi/tenant)
- Restructura Integraciones (5 paneles + UX unificada)
- Wipe coherente (`scripts/wipe_conversation.py`)
- Opción B invariant resumen-before-link
- FSM resolver orden pendiente (cross-conv shipping_quoted)
- shipping_phone update arquitectónico + Smells A/B (cambiar X por Y +
  bypass payment_link directo)
- **Bug A multi-variant input** (lista + refactor return prematuro)
- **Bug B cart-retake markers ampliados**

### Próxima sesión

**Decisión estratégica macro** discutida pero pendiente de resolución:
- Estrategia A (bot perfecto antes de prod) vs B (review_queue + handoff
  humano) vs C (architecture review puro).
- Founder rechazó B en esta sesión por preferencia de "no aceptar como
  imposible los bugs simples". Demostrado en la sesión: los 2 bugs A+B
  efectivamente eran arreglables sin parches.

**Items pendientes técnicos (no críticos)**:
- UAT scenarios nuevos para multi-variant + cart-retake (S29+, S30+).
- Plan PR strategy hacia `develop`/`main`.
- Cierre Fase 1 + autorización commit a `main`.

**Aprendizajes de sesión registrados**:
- Disciplina arquitectónica (no parches) funciona: cada bug se cerró con
  refactor del contrato/dominio del detector, sin regex sobre texto LLM.
- UAT manual del founder es complementario al UAT automatizado: cubre
  flows reales que UAT no codificó aún.
- Cuando el detector tiene un contrato "1 input → 1 output" en un
  dominio que naturalmente puede tener N matches (multi-variant), el
  contrato es el bug — no parche en el caller.

---

## ✅ Bug 1 — Saludo "Buenos días" duplicado — RESUELTO (commit 4c375d6)

### Síntomas observados (UAT founder 2026-05-19 ~16:18 UTC, conv b36ecb31)

```
T2 bot: "Buenos días! Soy Sara Camila de KAIU Living Natural. ¿En qué te ayudo?"
T3 cliente: "Que venden?"
T4 bot: "Buenos días! Soy Sara Camila de KAIU Living Natural. Trabajamos..."
```

Saludo + identidad completa duplicados en outbounds consecutivos del mismo
turno conversacional. Founder reportó "se siente extraño".

### Root cause

Prompt define "tu identidad: Sara Camila de KAIU" como bloque de persona.
LLM la re-incluye en outbounds posteriores al primero. Sin invariant
determinístico que lo prevenga, el LLM cae en este patrón.

### Fix arquitectónico aplicado (commit 4c375d6)

Nuevo invariant `assert_no_double_greeting()` en
`services/ai-orchestrator/outbound/invariants.py` (mismo patrón que
`time-aware-greeting` y `cordial-connector-for-direct-question`):
- Activa cuando NO es primer outbound de la conv Y candidato abre con
  "Buenos días/tardes/noches" o "Hola".
- Strippea el prefijo de saludo.
- Adicionalmente strippea "Soy {nombre} de {tenant}." si aparece directo
  tras el saludo (auto-presentación repetida).
- Capitaliza primera letra del remainder para que quede natural.

Invocado en `outbound/validator.validate()` como paso 0c, después de
time-aware-greeting (0a) y cordial-connector (0b).

### Tests
- `test_outbound_invariants.py::NoDoubleGreetingTests` (7 nuevos).

---

## ✅ Bug 2 — Categoría perdida (jabón → bot ofrece aceite) — RESUELTO (commit 5219c75)

### Síntomas observados (UAT founder 2026-05-19 ~16:18 UTC, conv b36ecb31)

```
T5 cliente: "Que jabones artesanales venden?"
T6 bot: lista 4 jabones específicos              ← framing 'jabón'
T7 cliente: "Me peudes vender 1 Jabon de Cogo y 1 de Lavanda"
T8 bot: "Confírmame la presentación de cada jabón"
T9 cliente: "Ok, deseo 1 de Coco 100g y 1 de Lavanda de 150g"
T10 bot: ❌ "Tenemos varios productos relacionados:
            * Aceite de Coco Virgen      ← NO, contexto era jabón
            * Jabón Artesanal de Coco
            * Jabón Artesanal de Lavanda"
```

Bot ofreció Aceite Coco como opción cuando contexto era jabón.

### Root cause (2 capas)

**Capa 1 — Detector contextual-blind**: `_detect_add_item_intent_with_resolution`
recibe `(content, catalog_completo)` sin filtro de contexto conversacional.
"coco" matchea Aceite Coco + Jabón Coco → `product_ambiguous`.

**Capa 2 — Atribución cruzada en multi-segment**: `_resolve_variant_from_inbound`
atribuía variantes cruzadas — el segmento "1 de Lavanda 150g" matcheaba la
variante 150g de Jabón Coco solo porque ese producto también tenía 150g,
sin verificar que el segmento mencionara "lavanda".

### Fix arquitectónico aplicado (commit 5219c75) — 5 capas sin parches

**Capa A** — `_extract_category_token_from_recent_context(history, catalog)`:
- Helper puro. Itera últimos N=5 mensajes (más reciente primero).
- Prefiere `category_head_words` (primer token significativo de cada
  título — sustantivos "jabon", "aceite") sobre `generic_terms` (que
  incluiría adjetivos como "artesanal").
- Despluralización ingenua (-s, -es) para español comercial.

**Capa B** — `_filter_catalog_by_category_token(catalog, token)`:
- Helper puro. Match por palabra exacta en title tokens. Back-compat: si
  filtro deja 0 productos → retorna catalog completo.

**Capa C** — `_resolve_variant_from_inbound(..., require_discriminative_per_segment=True)`:
- Nuevo parámetro opt-in (default False = back-compat con Bug A multi-variant).
- En multi-segment, cada segmento DEBE contener al menos 1 palabra
  discriminativa del título del producto (≥4 chars, no stop). Sin esto,
  el segmento se ignora para ese producto.

**Capa D** — tier-2: nueva resolución `resolved_multi`:
- Cuando `len(product_hits) > 1 AND has_explicit_variant AND cada uno
  tiene variante compatible resuelta` → retorna `matches=list[N]`.
- Antes era `product_ambiguous`; ahora reconoce N productos distintos
  con N variantes distintas.

**Capa E** — caller orchestrator (orchestrator.py:~7345):
- Antes de invocar tier-2 aplica capa A (extract) + capa B (filter).
  Loggea `[TIER2] category-lock 'jabon' aplicado`.
- Después de tier-2: nuevo handler para `resolution='resolved_multi'`
  que persiste cada match con `cart_tool.add_item` y deja que el flujo
  normal post-add continúe.

### Validación caso founder (test e2e)

```python
1. History b36ecb31 → category="jabon" ✓
2. Filter catalog → 3 jabones (sin aceites) ✓
3. Inbound "1 de Coco 100g y 1 de Lavanda 150g" + catalog filtrado →
   tier-2 = resolved_multi, matches = [Jabón Coco 100g, Jabón Lavanda 150g] ✓
```

### Tests
- `test_rev106_category_lock_multi_product.py` (21 nuevos):
  - `CategoryTokenExtractorTests` (8): edge cases del extractor.
  - `CatalogFilterByCategoryTests` (5): filtros y back-compat.
  - `ResolveVariantDiscriminativePerSegmentTests` (4): opt-in semántico.
  - `Tier2ResolvedMultiTests` (3): nueva resolución multi-product.
  - `IntegrationFounderBugScenarioTests` (1): caso exacto founder e2e.

### Lección registrada

La disciplina de separar concerns evita parches: el detector NO debe
"adivinar contexto" por sí mismo. El caller que conoce el history
gestiona contexto y pasa el catalog apropiado. El detector permanece
puro y testeable.

---

## Métricas sesión 2026-05-19 (cierre)

- Bugs runtime cerrados arquitectónicamente: **4** (A, B, 1, 2)
- Commits Sem 7 F2 cierre: 8+ (incluyendo address SIMPLIFY)
- Suite tests: 2040 verde (+50 vs inicio sesión)
- LOC `orchestrator.py`: estable (~8400, sin crecer significativamente
  por extracción a helpers puros).
