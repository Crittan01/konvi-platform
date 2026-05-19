# Bugs pendientes — rev. 106 (Sem 7 F2 cierre)

**Estado al cierre de sesión 2026-05-19 ~01:25 UTC.**

Sesión productiva de ~7h cerró Sem 7 F2 HSM templates completo, restructura
Integraciones, tenant-centric branding, y 3 bugs runtime arquitectónicos
arreglados (Opción B invariant, FSM orden pendiente, shipping_phone update).

UAT manual del founder descubrió 2 bugs nuevos NO arreglados en esta sesión
por scope/fatiga — requieren refactor mediano, NO parches. Documentados
acá para evitar pérdida de diagnóstico ya realizado.

---

## Bug A — Multi-variant input (1-2h)

### Síntoma observado

Conversación log `conversation_573125835649_20260519-012526.log` (T-13):

```
Cliente: "1 de 100ml y 1 de 250ml"   ← DOS items distintos
Bot:     "* 1x Aceite de Almendras Dulces (100ml): $28.000 COP"  ← solo uno
```

El bot interpretó como `1 de 100ml` y NUNCA evaluó el `1 de 250ml`.

### Root cause arquitectónico

`_resolve_variant_from_inbound` ([orchestrator.py:2409](services/ai-orchestrator/orchestrator.py#L2409))
tiene contrato **"1 inbound → 1 variant"**:

```python
def _resolve_variant_from_inbound(
    inbound_text: str, product: dict,
) -> tuple[Optional[dict], int]:
    # ... iterar variantes
    for v in variants:
        attrs = v.get("attributes") or {}
        for av in attrs.values():
            if av_n and av_n in norm and len(av_n) >= 2:
                return v, qty   ← RETURN inmediato al primer match
    # ...
```

Para "1 de 100ml y 1 de 250ml":
- Camino 1 matchea "100ml" → `return` con la única variante 100ml
- Nunca evalúa "250ml"

### Fix arquitectónico propuesto (NO parche)

Cambiar el contrato del detector a **"1 inbound → list[(variant, qty)]"**:

1. `_resolve_variant_from_inbound` retorna `list[tuple[variant, qty]]` (puede ser vacía, 1 elemento, o N).
2. `_extract_qty_for_product` debe segmentar por discriminador "y/+/," para asignar qty a cada variante.
3. `_detect_variant_confirmation` (línea 2944) cambia su retorno a `list[dict]` (cada uno con add_item params).
4. El caller que llama `cart_tool.add_item` itera la lista llamando una vez por variante.
5. Tests:
   - "1 de 100ml y 1 de 250ml" → 2 items distintos
   - "2 de 60g" → 1 item con qty=2 (caso ya cubierto, no regresión)
   - "60ml" → 1 item con qty=1 (default)
   - Edge case: "1 de 100ml y 250ml" (qty implícita)

### Impacto producción

Cliente que pide 2+ presentaciones del mismo producto pierde compras. En
catálogos cosmética (donde 60g + 100g de mismo producto es común) es
caso real frecuente.

---

## Bug B — Cart re-abrir post-orden (1-2h)

### Síntoma observado

Conversación log `conversation_573125835649_20260519-012526.log`:

| Turn | Estado |
|---|---|
| T-11 | Orden #27F9E02A creada con Jabón Coco. Link Wompi. |
| T-12 | Cliente: "Puedo agregar un Aceite de Almendras Dulces?" |
| T-13 | Bot resumen muestra **SOLO Aceite Almendras** (Jabón Coco desapareció) |

El bot dijo `"actualicé tu carrito. El link de pago anterior (*#27F9E02A*) ya no es válido."` pero el carrito perdió el item original.

### Root cause arquitectónico (hipótesis)

Cuando se crea orden + link Wompi, `conversation_carts.status` pasa de
`open` a `converted` (o `closed`). El cart "ya cumplió su función".

Cuando cliente luego pide add-item antes de pagar:
1. Bot invalida orden anterior (log: `[CART_INVALIDATE] resumen unificado emitido conv=...`)
2. `cart_tool.get_or_create_open_cart()` NO encuentra cart `status=open` → **crea uno nuevo vacío**
3. Add-item agrega el nuevo producto al cart NUEVO
4. Resumen muestra solo el item nuevo

Los items del cart `status=converted` quedan huérfanos asociados a orden
invalidada.

### Fix arquitectónico propuesto (NO parche)

Cuando se invalida orden (`_invalidate_order_for_cart_change`), también
**re-abrir el cart anterior** (status `converted` → `open`) en lugar de
crear nuevo:

1. En el path de `[CART_INVALIDATE]`, antes de `add_item`:
   - Buscar cart `status=converted` asociado a la orden invalidada
   - UPDATE `status=open` + reset `coupon_id` (cupón consumido se libera)
   - Marcar `requires_requote=True` (shipping puede variar con nuevo item)
2. Llamar `add_item` que ahora encuentra cart abierto con items originales + agrega el nuevo
3. Emitir resumen con TODOS los items + recotizar shipping

Alternativa (más limpia pero más invasiva): cuando se crea orden NO
cerrar el cart inmediatamente. Solo cerrar al confirmar pago (Wompi
APPROVED). Mientras orden está pending_payment, cart sigue open. Esto
elimina la asimetría "orden creada pero cart cerrado" que genera el bug.

### Verificación necesaria

Antes de aplicar fix:
- Confirmar lifecycle exacto de `conversation_carts.status` en código (ver
  ADR-0011 §6).
- Verificar si "re-abrir cart converted" rompe invariantes (ej. cupón ya
  consumido en `coupon_redemptions`).
- Validar UAT S13 (multi-product), S27, S28 que tocan cart lifecycle no
  regresionan.

### Impacto producción

Cliente que pide agregar producto después de generar link Wompi pero
antes de pagar pierde su pedido original. UX horrible:
- "Quiero agregar..." → "Listo, agregué" → cliente paga → recibe SOLO
  el item nuevo, no el original.

---

## Prioridades sugeridas próxima sesión

1. **Decisión estratégica macro** (review_queue vs seguir bug-by-bug) — 1h conversación
2. Bug A multi-variant (~1-2h fix arquitectónico)
3. Bug B cart re-abrir post-orden (~1-2h fix arquitectónico)
4. Tests UAT nuevos para cubrir ambos flows
5. Cierre commit consolidado + plan PR a `develop`

Total estimado próxima sesión: ~6h si abordamos todo. Si decidimos
estrategia B (review_queue + handoff humano), estos 2 bugs entrarían
cubiertos por escalación + se priorizarían según demanda real producción.

---

## Lo que SÍ se cerró esta sesión (commits en `phase-0-pre-prod`)

- Sem 7 F2 HSM templates engine completo (items 1-7)
- ADR-0016 HSM templates engine
- Tenant-centric branding (segregación Konvi/tenant)
- Restructura Integraciones (5 paneles + UX unificada)
- Wipe coherente (`scripts/wipe_conversation.py`)
- Fix arquitectónico Opción B (invariant resumen-before-link)
- Fix arquitectónico FSM resolver orden pendiente
- Fix arquitectónico shipping_phone update PRE_BYPASS + Smells A/B

**Total commits sesión rev. 106**: 85+ acumulados en `phase-0-pre-prod`
listos para mergear cuando se defina estrategia PR (1 grande / 3
lógicos / acumular).
