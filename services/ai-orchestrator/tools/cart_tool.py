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
                "shipping_meta, requires_requote, contact_id")
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
                ).eq("id", cart["id"]).execute()
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
                "shipping_meta, requires_requote, contact_id")
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
    """
    if quantity < 1:
        raise ValueError("add_item: quantity debe ser >= 1")
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
    invalidate_shipping(supabase, cart_id=cart_id, reason="item_added")
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
    ).eq("variation_id", variation_id).execute()
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
    """Borra el item del carrito + recalcula totals + invalida shipping."""
    supabase.table("conversation_cart_items").delete().eq(
        "cart_id", cart_id
    ).eq("variation_id", variation_id).execute()
    # Recalcular subtotal manualmente.
    items = (
        supabase.table("conversation_cart_items")
        .select("quantity, unit_price_cents")
        .eq("cart_id", cart_id)
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
    invalidate_shipping(supabase, cart_id=cart_id, reason="item_removed")
    return {"cart_id": cart_id, "new_subtotal_cents": new_subtotal}


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
    service_level: str,
    rate_id: Optional[str],
    city: str,
    dane_code: Optional[str],
    address_line: Optional[str],
    weight_inputs: dict,
    shipping_cents: int,
) -> dict:
    """Persiste la rate Envia elegida + recalcula totals + clear requires_requote."""
    # Leer subtotal actual para recomputar total.
    cur = (
        supabase.table("conversation_carts")
        .select("subtotal_cents")
        .eq("id", cart_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not cur.data:
        raise RuntimeError(f"set_shipping_meta: cart {cart_id} no encontrado")
    subtotal = int(cur.data[0].get("subtotal_cents") or 0)
    new_total = subtotal + int(shipping_cents)

    shipping_meta = {
        "carrier": carrier,
        "service_level": service_level,
        "rate_id": rate_id,
        "city": city,
        "dane_code": dane_code,
        "address_line": address_line,
        "weight_inputs": weight_inputs,
        "shipping_cents": int(shipping_cents),
    }
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


def invalidate_shipping(
    supabase: Client,
    *,
    cart_id: str,
    reason: str = "item_changed",
) -> dict:
    """Setea requires_requote=true + reset shipping_cents=0. Conserva
    address en shipping_meta para que el bot no tenga que repreguntar."""
    cur = (
        supabase.table("conversation_carts")
        .select("shipping_meta, subtotal_cents")
        .eq("id", cart_id)
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
    new_total = int(row.get("subtotal_cents") or 0)
    supabase.table("conversation_carts").update({
        "shipping_cents": 0,
        "shipping_meta": preserved,
        "total_cents": new_total,
        "requires_requote": True,
    }).eq("id", cart_id).execute()
    logger.info("[CART] shipping invalidated cart=%s reason=%s", cart_id[:8], reason)
    return {"cart_id": cart_id, "invalidated": True, "reason": reason}
