"""
Cart tool — Rev. 80.

El carrito vive en `conversation_carts` + `conversation_cart_items` (DB) como
única fuente de verdad. El LLM se usa para extraer intent; este módulo
persiste y consulta el estado.

Funciones expuestas:
    ensure_cart            — devuelve cart 'open' o lo crea (idempotente).
    add_item               — invoca RPC cart_add_item + invalida shipping.
    update_item_quantity   — same RPC (es UPSERT) + invalida shipping.
    remove_item            — DELETE + invalida shipping.
    get_cart_with_items    — SELECT con JOIN a product_variations (dims).
    compute_shipping_inputs — peso físico + volumétrico + billable.
    set_shipping_meta      — persiste rate Envia + recalcula totales.
    invalidate_shipping    — flag requires_requote=true + reset shipping_cents.

Reuso:
    RPC `cart_add_item` (migración 20260501000000): upsert atómico,
    version locking, recálculo subtotal/total.

Volumetría: usa la heurística cúbica `dim·qty^(1/3)` para approximar
packing realista (la misma de shipping_quote_tool._scale_dimension).
Peso volumétrico canónico de courier = volumen_cm3 / 5000.
"""
from __future__ import annotations

import logging
from typing import Optional

from supabase import Client

logger = logging.getLogger("orchestrator.tools.cart")


def _emit_cart_event(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: Optional[str],
    event_type: str,
    payload: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Wrapper best-effort sobre `cart.events.emit`.

    Se importa lazy para evitar circulares (cart/events.py no debe depender
    de tools/cart_tool.py). Cualquier fallo es swalloweado: la auditoría
    nunca debe bloquear la mutación funcional del cart.
    """
    if not tenant_id:
        return
    try:
        from cart.events import emit as _emit
        _emit(
            supabase,
            cart_id=cart_id,
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload or {},
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[CART_EVENT] emit wrapper falló: %s", exc)


def invalidate_pending_order_on_cart_change(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    reason: str,
) -> Optional[dict]:
    """Si la conversación del cart tiene una `orders.pending_payment` activa,
    cancelarla + marcar `payments.pending` como `voided`.

    Plan A.0.1 (cart-as-SoT, ADR-0011): toda mutación del cart con orden
    activa rompe el contrato "una conv = una orden con un total acordado".
    El link Wompi ya generado tiene un `amount_in_cents` congelado al momento
    de crear la orden y NO se actualiza con el cart. Si el cliente paga el
    link viejo después de modificar el cart, el monto pagado diverge del cart
    real → pérdida o queja.

    La invalidación es síncrona y precede al cambio del cart: si esto falla,
    NO mutamos el cart (mejor rechazar la modificación que dejar inconsistencia).

    Retorna:
      None si no había orden activa (caso normal: cliente todavía construyendo
      el cart antes de generar link).
      dict {order_id, voided_payment_count, reason} si invalidó algo. El
      caller (orchestrator) usa este dict para informar al cliente que el
      link anterior ya no es válido.

    Args:
      cart_id: identifica la conversación (cart → conversation_id).
      tenant_id: scope multi-tenant.
      reason: motivo de la invalidación (ej. 'item_added', 'item_removed',
              'qty_changed'). Se persiste en notes y en cart_events.
    """
    # Resolver conversation_id desde el cart.
    try:
        cart_res = (
            supabase.table("conversation_carts")
            .select("conversation_id")
            .eq("id", cart_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[CART_INVALIDATE] no pude leer cart=%s: %s — skip invalidation",
            cart_id[:8], exc,
        )
        return None
    cart_rows = cart_res.data if isinstance(cart_res.data, list) else []
    if not cart_rows or not isinstance(cart_rows[0], dict):
        return None
    conversation_id = cart_rows[0].get("conversation_id")
    if not conversation_id:
        return None

    # Buscar orden pending_payment activa para esta conversación.
    try:
        orders_res = (
            supabase.table("orders")
            .select("id, total_amount, notes")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("status", "pending_payment")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[CART_INVALIDATE] lookup orders falló conv=%s: %s",
            str(conversation_id)[:8], exc,
        )
        return None
    orders_data = orders_res.data if isinstance(orders_res.data, list) else []
    if not orders_data or not isinstance(orders_data[0], dict):
        return None  # No hay orden activa — caso normal
    order = orders_data[0]
    order_id = order.get("id")
    if not order_id:
        return None

    # Cancelar orden con motivo cart_modified.
    try:
        from datetime import datetime, timezone
        prior_notes = str(order.get("notes") or "")
        new_notes = (
            f"{prior_notes} | cancelled_due_to_cart_change={reason}"
            if prior_notes else f"cancelled_due_to_cart_change={reason}"
        )
        supabase.table("orders").update({
            "status": "cancelled",
            "notes": new_notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", order_id).eq("tenant_id", tenant_id).eq(
            "status", "pending_payment"  # CAS: no pisar otros estados
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[CART_INVALIDATE] no pude cancelar order=%s: %s",
            str(order_id)[:8], exc,
        )
        return None

    # Voided todos los payments.pending de esta orden.
    voided_count = 0
    try:
        upd = (
            supabase.table("payments")
            .update({"status": "voided"})
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id)
            .eq("status", "pending")
            .execute()
        )
        voided_count = len(upd.data or []) if isinstance(upd.data, list) else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[CART_INVALIDATE] no pude voided payments order=%s: %s — orden ya cancelada",
            str(order_id)[:8], exc,
        )

    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="order_invalidated_due_to_cart_change",
        payload={
            "order_id": order_id,
            "reason": reason,
            "voided_payment_count": voided_count,
            "previous_total_amount": float(order.get("total_amount") or 0),
        },
    )
    logger.info(
        "[CART_INVALIDATE] order=%s cancelada + %d payment(s) voided por reason=%s",
        str(order_id)[:8], voided_count, reason,
    )
    return {
        "order_id": order_id,
        "voided_payment_count": voided_count,
        "reason": reason,
    }


# ─── Cart lifecycle ──────────────────────────────────────────────────────────

def ensure_cart(
    supabase: Client,
    *,
    conversation_id: str,
    tenant_id: str,
    contact_id: Optional[str] = None,
) -> dict:
    """Devuelve cart con status='open' para la conversación, o lo crea.

    Idempotente: si ya existe un cart 'open', no crea otro (UNIQUE constraint
    aplica en la migración).
    """
    res = (
        supabase.table("conversation_carts")
        .select("id, status, version, subtotal_cents, shipping_cents, total_cents, "
                "shipping_meta, requires_requote, contact_id, "
                "coupon_id, coupon_code, discount_cents")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conversation_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if res.data:
        cart = res.data[0]
        # Si el cart abierto no tiene contact_id pero ahora lo conocemos, asociar.
        if contact_id and not cart.get("contact_id"):
            try:
                supabase.table("conversation_carts").update(
                    {"contact_id": contact_id}
                ).eq("id", cart["id"]).eq("tenant_id", tenant_id).execute()
                cart["contact_id"] = contact_id
            except Exception as exc:
                logger.warning("[CART] No pude asociar contact_id=%s a cart=%s: %s",
                               contact_id, cart["id"], exc)
        return cart

    # No hay cart abierto — crear uno nuevo.
    insert = (
        supabase.table("conversation_carts")
        .insert({
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "status": "open",
        })
        .execute()
    )
    cart = (insert.data or [None])[0]
    if not cart:
        raise RuntimeError(f"ensure_cart: insert no devolvió fila para conv={conversation_id}")
    logger.info("[CART] creado cart=%s conv=%s tenant=%s", cart["id"][:8],
                conversation_id[:8], tenant_id[:8])
    return cart


def get_cart_with_items(
    supabase: Client,
    *,
    conversation_id: str,
    tenant_id: str,
) -> Optional[dict]:
    """Retorna cart abierto + items + dims de variations, o None.

    Estructura devuelta:
        {
          id, status, version, subtotal_cents, shipping_cents, total_cents,
          shipping_meta, requires_requote, contact_id,
          items: [{
            id, variation_id, product_id, quantity, unit_price_cents,
            variation: {weight_kg, length_cm, width_cm, height_cm, label, ...},
            product: {title, ...}
          }, ...]
        }
    """
    cart_res = (
        supabase.table("conversation_carts")
        .select("id, status, version, subtotal_cents, shipping_cents, total_cents, "
                "shipping_meta, requires_requote, contact_id, "
                "coupon_id, coupon_code, discount_cents, payment_method")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conversation_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not cart_res.data:
        return None
    cart = cart_res.data[0]

    items_res = (
        supabase.table("conversation_cart_items")
        .select("id, variation_id, product_id, quantity, unit_price_cents, meta, created_at")
        .eq("cart_id", cart["id"])
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=False)
        .execute()
    )
    items = items_res.data or []

    if items:
        var_ids = list({i["variation_id"] for i in items if i.get("variation_id")})
        prod_ids = list({i["product_id"] for i in items if i.get("product_id")})
        var_lookup: dict = {}
        prod_lookup: dict = {}
        if var_ids:
            # Rev. 103 — schema real de `product_variations` NO tiene columnas
            # `label` ni `presentation`. La etiqueta de la variante se deriva
            # del JSONB `attributes` (ej. {"size": "60g"} → label "60g").
            vres = (
                supabase.table("product_variations")
                .select("id, attributes, weight_kg, length_cm, "
                        "width_cm, height_cm, sku")
                .in_("id", var_ids)
                .eq("tenant_id", tenant_id)  # A6.2.7: defensa cross-tenant
                .execute()
            )
            var_lookup = {}
            for r in (vres.data or []):
                attrs = r.get("attributes") or {}
                if isinstance(attrs, dict) and attrs:
                    # Concatena los valores de attributes en orden
                    # (típicamente solo "size": "60g" → "60g").
                    derived_label = " ".join(
                        str(v).strip() for v in attrs.values() if v
                    ).strip()
                    r["label"] = derived_label or r.get("sku") or ""
                    r["presentation"] = derived_label
                else:
                    r["label"] = r.get("sku") or ""
                    r["presentation"] = ""
                var_lookup[r["id"]] = r
        if prod_ids:
            # Rev. 103 — schema real `products` solo tiene `title` (no `name`
            # ni `brand`). El downstream usa `name` como alias — sintetizar
            # desde title para compat.
            pres = (
                supabase.table("products")
                .select("id, title")
                .in_("id", prod_ids)
                .eq("tenant_id", tenant_id)  # A6.2.7: defensa cross-tenant
                .execute()
            )
            prod_lookup = {}
            for r in (pres.data or []):
                r["name"] = r.get("title")  # alias para downstream
                r["brand"] = ""
                prod_lookup[r["id"]] = r
        for it in items:
            it["variation"] = var_lookup.get(it.get("variation_id")) or {}
            it["product"] = prod_lookup.get(it.get("product_id")) or {}
    cart["items"] = items
    return cart


# ─── Item mutations ──────────────────────────────────────────────────────────

def add_item(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    product_id: str,
    variation_id: str,
    quantity: int,
    unit_price_cents: int,
    expected_version: Optional[int] = None,
) -> dict:
    """Invoca RPC cart_add_item (UPSERT atómico) + invalida shipping.

    Si el cart ya tiene esta variation, suma la quantity (RPC lo maneja).

    Plan A.0.1 / ADR-0011: si la conversación tiene una orden
    `pending_payment` activa, antes del cambio se invalida (cancela orden
    + voided payments). El campo `order_invalidated` en el payload retornado
    señaliza al caller (orchestrator) para que informe al cliente que el
    link anterior ya no es válido.
    """
    if quantity < 1:
        raise ValueError("add_item: quantity debe ser >= 1")
    invalidated = invalidate_pending_order_on_cart_change(
        supabase, cart_id=cart_id, tenant_id=tenant_id, reason="item_added",
    )
    res = supabase.rpc(
        "cart_add_item",
        {
            "p_tenant_id": tenant_id,
            "p_cart_id": cart_id,
            "p_product_id": product_id,
            "p_variation_id": variation_id,
            "p_quantity": quantity,
            "p_unit_price_cents": unit_price_cents,
            "p_expected_version": expected_version,
        },
    ).execute()
    payload = (res.data or [None])[0] if isinstance(res.data, list) else res.data
    if not payload:
        raise RuntimeError(f"add_item: RPC no devolvió payload (cart={cart_id})")
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="item_added",
        payload={
            "product_id": product_id,
            "variation_id": variation_id,
            "quantity": int(quantity),
            "unit_price_cents": int(unit_price_cents),
        },
    )
    invalidate_shipping(
        supabase, cart_id=cart_id, tenant_id=tenant_id, reason="item_added",
    )
    if isinstance(payload, dict) and invalidated:
        payload["order_invalidated"] = invalidated
    return payload


def update_item_quantity(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    product_id: str,
    variation_id: str,
    new_quantity: int,
    unit_price_cents: int,
) -> dict:
    """Cambia la cantidad de un item.

    El RPC cart_add_item suma quantity al existente (no reemplaza). Para
    UPDATE absoluto, hacemos DELETE del item + INSERT con la nueva qty.
    Esto mantiene atomicidad y dispara recálculo de totals via trigger
    (si existe) o lo hacemos explícito.
    """
    if new_quantity < 1:
        # qty=0 → tratar como remove
        return remove_item(
            supabase,
            cart_id=cart_id,
            tenant_id=tenant_id,
            variation_id=variation_id,
        )
    # DELETE existente + INSERT con new_quantity (atomic via SECURITY DEFINER RPC).
    supabase.table("conversation_cart_items").delete().eq(
        "cart_id", cart_id
    ).eq("variation_id", variation_id).eq("tenant_id", tenant_id).execute()
    return add_item(
        supabase,
        cart_id=cart_id,
        tenant_id=tenant_id,
        product_id=product_id,
        variation_id=variation_id,
        quantity=new_quantity,
        unit_price_cents=unit_price_cents,
    )


def remove_item(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    variation_id: str,
) -> dict:
    """Borra el item del carrito + recalcula totals + invalida shipping.

    Plan A.0.1 / ADR-0011: si la conversación tiene orden `pending_payment`
    activa, se invalida antes del cambio (ver add_item).
    """
    invalidated = invalidate_pending_order_on_cart_change(
        supabase, cart_id=cart_id, tenant_id=tenant_id, reason="item_removed",
    )
    supabase.table("conversation_cart_items").delete().eq(
        "cart_id", cart_id
    ).eq("variation_id", variation_id).eq("tenant_id", tenant_id).execute()
    # Recalcular subtotal manualmente.
    items = (
        supabase.table("conversation_cart_items")
        .select("quantity, unit_price_cents")
        .eq("cart_id", cart_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    new_subtotal = sum(
        int(i.get("quantity") or 0) * int(i.get("unit_price_cents") or 0)
        for i in (items.data or [])
    )
    # Mantener shipping_cents pero marcar requires_requote.
    supabase.table("conversation_carts").update({
        "subtotal_cents": new_subtotal,
        "total_cents": new_subtotal,  # shipping queda invalidado abajo
    }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="item_removed",
        payload={
            "variation_id": variation_id,
            "new_subtotal_cents": new_subtotal,
        },
    )
    invalidate_shipping(
        supabase, cart_id=cart_id, tenant_id=tenant_id, reason="item_removed",
    )
    result = {"cart_id": cart_id, "new_subtotal_cents": new_subtotal}
    if invalidated:
        result["order_invalidated"] = invalidated
    return result


# ─── Shipping computation ────────────────────────────────────────────────────

def _scale_dim(base: float, qty: int) -> float:
    """Escala una dimensión por cube root de qty (heurística packing)."""
    if qty <= 1:
        return float(base)
    return round(float(base) * (qty ** (1.0 / 3.0)), 2)


def compute_shipping_inputs(cart: dict) -> dict:
    """Lee items del cart (con su `variation` JOINed) y computa peso + dims
    para enviar a Envia.

    Reglas:
        • Peso físico total = Σ (weight_kg × quantity).
        • Por línea: dims efectivas = base × qty^(1/3).
        • Volumen línea = L_eff × W_eff × H_eff (cm³).
        • Volumetric_kg línea = volumen / 5000 (canon courier internacional).
        • Total volumetric_kg = Σ (volumetric_kg línea).
        • Billable_weight_kg = max(peso_físico, volumetric).
        • Package dims: bounding box approx tomando la línea más grande
          (el courier usualmente cobra por el item más voluminoso del bulto).

    Si una variation no tiene weight_kg/dims, usa 0.0 con warning.
    """
    items = cart.get("items") or []
    if not items:
        return {
            "weight_kg": 0.0,
            "volumetric_weight_kg": 0.0,
            "billable_weight_kg": 0.0,
            "package_dims": {"length_cm": 0.0, "width_cm": 0.0, "height_cm": 0.0},
            "lines": [],
        }

    total_weight = 0.0
    total_volumetric = 0.0
    lines = []
    max_line_dims = (0.0, 0.0, 0.0)

    for it in items:
        qty = int(it.get("quantity") or 1)
        v = it.get("variation") or {}
        w = float(v.get("weight_kg") or 0.0)
        L = float(v.get("length_cm") or 0.0)
        W = float(v.get("width_cm") or 0.0)
        H = float(v.get("height_cm") or 0.0)

        if w <= 0 or L <= 0 or W <= 0 or H <= 0:
            logger.warning(
                "[CART] variation %s con dims/peso incompleto (qty=%s, w=%s, L=%s, W=%s, H=%s)",
                it.get("variation_id"), qty, w, L, W, H,
            )

        L_eff = _scale_dim(L, qty)
        W_eff = _scale_dim(W, qty)
        H_eff = _scale_dim(H, qty)
        line_volume_cm3 = L_eff * W_eff * H_eff
        line_volumetric_kg = round(line_volume_cm3 / 5000.0, 3)
        line_physical_kg = round(w * qty, 3)

        total_weight += line_physical_kg
        total_volumetric += line_volumetric_kg
        if line_volume_cm3 > max_line_dims[0] * max_line_dims[1] * max_line_dims[2]:
            max_line_dims = (L_eff, W_eff, H_eff)

        lines.append({
            "variation_id": it.get("variation_id"),
            "quantity": qty,
            "weight_kg": w,
            "length_cm": L,
            "width_cm": W,
            "height_cm": H,
            "scaled_dims": {"length_cm": L_eff, "width_cm": W_eff, "height_cm": H_eff},
            "line_physical_kg": line_physical_kg,
            "line_volumetric_kg": line_volumetric_kg,
        })

    billable = max(total_weight, total_volumetric)
    return {
        "weight_kg": round(total_weight, 3),
        "volumetric_weight_kg": round(total_volumetric, 3),
        "billable_weight_kg": round(billable, 3),
        "package_dims": {
            "length_cm": max_line_dims[0],
            "width_cm": max_line_dims[1],
            "height_cm": max_line_dims[2],
        },
        "lines": lines,
    }


# ─── Shipping persistence ────────────────────────────────────────────────────

def set_shipping_meta(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    carrier: str,
    service_level: str = "",
    rate_id: Optional[str] = None,
    city: Optional[str] = None,
    dane_code: Optional[str] = None,
    address_line: Optional[str] = None,
    weight_inputs: Optional[dict] = None,
    shipping_cents: int = 0,
) -> dict:
    """Persiste la rate Envia elegida + recalcula totals + clear requires_requote.

    Rev. 103 — todos los campos meta son opcionales para que el orchestrator
    pueda persistir cart shipping con info parcial (carrier + cents) cuando
    detecta selección post-quote, y luego enriquecerla si shipping_quote_tool
    corre con datos completos. El total siempre se recalcula coherente.
    """
    # Leer subtotal + shipping_meta actual para preservar quoted_options
    # y demás campos extendidos (rev. 107: bug runtime KAIU 94b0078c —
    # set_shipping_meta sobrescribía shipping_meta perdiendo quoted_options,
    # rompiendo el fuzzy match de select_carrier en re-selecciones).
    cur = (
        supabase.table("conversation_carts")
        .select("subtotal_cents, shipping_meta, discount_cents")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        raise RuntimeError(f"set_shipping_meta: cart {cart_id} no encontrado")
    subtotal = int(cur.data[0].get("subtotal_cents") or 0)
    # Rev. 109 fix UAT live BUG 34 — preservar descuento de cupón ya
    # aplicado. Sin este max(), set_shipping_meta sobrescribía total_cents
    # ignorando discount_cents → cliente perdía el descuento al elegir
    # carrier post-cupón.
    discount = int(cur.data[0].get("discount_cents") or 0)
    new_total = max(0, subtotal + int(shipping_cents) - discount)
    existing_meta = cur.data[0].get("shipping_meta") or {}

    # Merge: actualizar campos canónicos del carrier seleccionado +
    # preservar quoted_options (lista de opciones cotizadas para re-select).
    shipping_meta = {
        **existing_meta,
        "carrier": carrier,
        "service_level": service_level,
        "shipping_cents": int(shipping_cents),
    }
    # A11 audit 2026-06-25 (CART-01): preservar campos enriquecibles previos
    # cuando el caller pasa info parcial (None). El docstring promete persistir
    # parcial (carrier+cents) "y luego enriquecerla" — pero el merge plano los
    # nulificaba. Callers reales (orchestrator.py:5176, legacy_adapters/cart.py)
    # pasan carrier+cents SIN city/dane/address → se perdían → requote roto +
    # link Wompi con shipping stale.
    for _k, _v in (
        ("rate_id", rate_id),
        ("city", city),
        ("dane_code", dane_code),
        ("address_line", address_line),
        ("weight_inputs", weight_inputs),
    ):
        if _v is not None:
            shipping_meta[_k] = _v
    (
        supabase.table("conversation_carts")
        .update({
            "shipping_cents": int(shipping_cents),
            "shipping_meta": shipping_meta,
            "total_cents": new_total,
            "requires_requote": False,
        })
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    logger.info(
        "[CART] shipping_meta set cart=%s carrier=%s service=%s shipping=%s subtotal=%s total=%s",
        cart_id[:8], carrier, service_level, shipping_cents, subtotal, new_total,
    )
    # Evento canónico: carrier_selected — el cliente eligió Económica/Rápida.
    # Si shipping_cents=0 (quote inicial sin selección aún) emitimos shipping_quoted
    # en su lugar; cuando llega selección real, el call siguiente reemite.
    _evt = "carrier_selected" if int(shipping_cents) > 0 else "shipping_quoted"
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type=_evt,
        payload={
            "carrier": carrier,
            "service_level": service_level,
            "rate_id": rate_id,
            "city": city,
            "shipping_cents": int(shipping_cents),
            "total_cents": new_total,
        },
    )
    # Devolvemos el snapshot computado, no la fila del UPDATE — el caller
    # solo necesita los nuevos totales y la meta para mostrar al cliente.
    return {
        "id": cart_id,
        "shipping_cents": int(shipping_cents),
        "subtotal_cents": subtotal,
        "total_cents": new_total,
        "shipping_meta": shipping_meta,
        "requires_requote": False,
    }


def set_shipping_recipient(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    name: str | None = None,
    document_type: str | None = None,
    document_number: str | None = None,
    phone: str | None = None,
    address: dict | None = None,
) -> dict:
    """Persiste destinatario alterno (regalo / envío a tercero) en
    cart.shipping_meta.recipient_* — NO sobrescribe contact del titular.

    Rev. 109 fix UAT live BUG 37 (Habeas Data Ley 1581) — cuando el
    cliente compra para otra persona ("es para mi mamá") los datos del
    receptor deben vivir en el cart (orden específica) NO en el contact
    del titular WhatsApp. Sin esto, el bot sobrescribía Cristian → María
    en contacts table → violación Habeas Data + UX rota.

    Cualquier campo en None se preserva del valor anterior (parcial-merge).
    Para borrar el recipient completo, pasar todos los campos vacíos o
    invocar clear_shipping_recipient.
    """
    cur = (
        supabase.table("conversation_carts")
        .select("shipping_meta")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        raise RuntimeError(f"set_shipping_recipient: cart {cart_id} no encontrado")
    existing_meta = cur.data[0].get("shipping_meta") or {}
    existing_recipient = existing_meta.get("recipient") or {}

    new_recipient = {
        "name": (name if name is not None
                 else existing_recipient.get("name")),
        "document_type": (document_type if document_type is not None
                          else existing_recipient.get("document_type")),
        "document_number": (document_number if document_number is not None
                            else existing_recipient.get("document_number")),
        "phone": (phone if phone is not None
                  else existing_recipient.get("phone")),
        "address": (address if address is not None
                    else existing_recipient.get("address")),
    }
    new_meta = {**existing_meta, "recipient": new_recipient}

    supabase.table("conversation_carts").update({
        "shipping_meta": new_meta,
    }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()

    logger.info(
        "[CART] shipping_recipient set cart=%s name=%s doc=%s phone=%s",
        cart_id[:8], new_recipient.get("name"),
        new_recipient.get("document_number"),
        new_recipient.get("phone"),
    )
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="shipping_recipient_set",
        payload={"recipient": new_recipient},
    )
    return {"cart_id": cart_id, "recipient": new_recipient}


def set_quoted_options(
    supabase: Client,
    *,
    cart_id: str,
    tenant_id: str,
    options: list[dict],
) -> dict:
    """Persiste en cart.shipping_meta.quoted_options el array completo de
    opciones cotizadas (rate_id + carrier + service + price + eta).

    Rev. 106 — fix bug `RATE_ID_NOT_CACHED` (conv 2eb3bb48, 2026-05-22):
    el cache de opciones vivía solo en ctx.extras (memoria volátil que se
    resetea cada turn). Cuando el legacy cotizaba (fallback) y el agentic
    intentaba seleccionar carrier en turn siguiente, no tenía rate_ids.

    DB-first (Plan A.0.2): ambos paths (legacy + agentic) leen del mismo
    lugar canónico. No toca carrier/service/cents — solo añade las opciones
    disponibles para que `select_carrier` pueda resolverlas.

    Args:
        options: lista de dicts {rate_id, carrier, service_level,
            price_cents, eta_date, currency}.

    Returns:
        dict snapshot del shipping_meta actualizado.
    """
    cur = (
        supabase.table("conversation_carts")
        .select("shipping_meta")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        raise RuntimeError(f"set_quoted_options: cart {cart_id} no encontrado")

    existing_meta = cur.data[0].get("shipping_meta") or {}
    # Sanitizar opciones — solo persistir campos canónicos.
    sanitized = []
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        rid = str(opt.get("rate_id") or opt.get("id") or "").strip()
        if not rid:
            continue
        sanitized.append({
            "rate_id": rid,
            "carrier": str(opt.get("carrier") or "").strip(),
            "service_level": str(
                opt.get("service_level") or opt.get("service") or ""
            ).strip(),
            "price_cents": int(opt.get("price_cents") or 0),
            "eta_date": str(opt.get("eta_date") or opt.get("eta") or "").strip(),
            "currency": str(opt.get("currency") or "COP").strip(),
        })
    if not sanitized:
        logger.warning(
            "[CART] set_quoted_options: array vacío post-sanitize cart=%s",
            cart_id[:8],
        )
        return {"id": cart_id, "shipping_meta": existing_meta}

    new_meta = dict(existing_meta)
    new_meta["quoted_options"] = sanitized
    (
        supabase.table("conversation_carts")
        .update({"shipping_meta": new_meta})
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    logger.info(
        "[CART] quoted_options persisted cart=%s n=%d rate_ids=%s",
        cart_id[:8], len(sanitized),
        [o["rate_id"][:8] for o in sanitized[:3]],
    )
    return {"id": cart_id, "shipping_meta": new_meta}


def set_shipping_city(
    supabase: Client,
    *,
    cart_id: str,
    new_city: str,
    new_dane_code: str | None = None,
    tenant_id: str,
) -> dict:
    """Rev. 104 (F0-3 / BUG-1): registra cambio de ciudad post-cotización.

    Cuando el cliente dice "cambia el envío a Medellín" tras haber cotizado
    a Bogotá, el cart debe:
      • Marcar `requires_requote=True` (cotización vieja inválida).
      • Registrar la nueva `city` (y `dane_code` si se conoce) en
        `shipping_meta` para que el next quote tenga el destino correcto.
      • Limpiar `shipping_cents=0` y carrier (la próxima quote los re-llena).

    El bot debe llamar esto ANTES de la nueva cotización; el `_persist_cart_shipping_if_needed`
    posterior actualizará todos los campos cuando el cliente seleccione carrier.
    """
    cur = (
        supabase.table("conversation_carts")
        .select("shipping_meta, subtotal_cents, discount_cents")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        return {"cart_id": cart_id, "updated": False}
    row = cur.data[0]
    meta = row.get("shipping_meta") or {}
    # Reset campos de quote vieja (carrier, service, rate_id) y override city.
    new_meta = {
        "city": new_city,
        "dane_code": new_dane_code or meta.get("dane_code"),
        "address_line": meta.get("address_line"),
        "weight_inputs": meta.get("weight_inputs"),
        "city_changed_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    # Rev. 109 fix UAT live BUG 34 — preservar discount aplicado por cupón.
    _disc = int(row.get("discount_cents") or 0)
    new_total = max(0, int(row.get("subtotal_cents") or 0) - _disc)
    supabase.table("conversation_carts").update({
        "shipping_cents": 0,
        "shipping_meta": new_meta,
        "total_cents": new_total,
        "requires_requote": True,
    }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    logger.info(
        "[CART] shipping_city=%s cart=%s — requires_requote=True, prev city=%s",
        new_city, cart_id[:8], meta.get("city"),
    )
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="city_changed",
        payload={
            "prev_city": meta.get("city"),
            "new_city": new_city,
            "new_dane_code": new_dane_code,
        },
    )
    return {
        "cart_id": cart_id, "updated": True,
        "new_city": new_city, "prev_city": meta.get("city"),
    }


def invalidate_shipping(
    supabase: Client,
    *,
    cart_id: str,
    reason: str = "item_changed",
    tenant_id: str,
) -> dict:
    """Setea requires_requote=true + reset shipping_cents=0. Conserva
    address en shipping_meta para que el bot no tenga que repreguntar."""
    cur = (
        supabase.table("conversation_carts")
        .select("shipping_meta, subtotal_cents, discount_cents")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        return {"cart_id": cart_id, "invalidated": False}
    row = cur.data[0]
    meta = row.get("shipping_meta") or {}
    # Conservar address (city, dane_code, address_line) y limpiar el resto.
    preserved = {
        k: meta.get(k)
        for k in ("city", "dane_code", "address_line")
        if meta.get(k)
    }
    preserved["invalidated_reason"] = reason
    # Rev. 109 fix UAT live BUG 34 — preservar discount aplicado.
    _disc = int(row.get("discount_cents") or 0)
    new_total = max(0, int(row.get("subtotal_cents") or 0) - _disc)
    supabase.table("conversation_carts").update({
        "shipping_cents": 0,
        "shipping_meta": preserved,
        "total_cents": new_total,
        "requires_requote": True,
    }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    logger.info("[CART] shipping invalidated cart=%s reason=%s", cart_id[:8], reason)
    _emit_cart_event(
        supabase,
        cart_id=cart_id, tenant_id=tenant_id,
        event_type="shipping_invalidated",
        payload={"reason": reason, "preserved_city": preserved.get("city")},
    )
    return {"cart_id": cart_id, "invalidated": True, "reason": reason}
