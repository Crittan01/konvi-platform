# Bugs Sem 7 F2 cierre — historial completo

**Estado al cierre de sesión 2026-05-19 ~02:25 UTC.**

Documento histórico de los 2 bugs descubiertos en UAT manual del founder
durante la sesión Sem 7 F2 cierre. **Ambos arreglados arquitectónicamente
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
