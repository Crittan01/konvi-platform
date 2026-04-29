"""Handlers de tools de envío.

Tools cubiertos:
  - ``quote_shipping``  → cotiza con Envia desde el carrito persistido (NO
    re-deriva del history). Persiste rate_id + costo en
    ``conversation_carts.shipping_meta`` + ``shipping_cents``.
  - ``select_carrier``  → confirma elección entre Económica/Rápida.

Diferencia fundamental con la versión vieja:
  - Lee ``ctx.cart.items`` como fuente de verdad. El paquete se calcula
    sumando peso y dimensiones de las variantes reales del carrito.
  - NO hay regex sobre el historial. NO hay falsos positivos por apellidos
    que coincidan con ciudad ("Garzón" ≠ destino).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client

from core.context import ConversationContext
from persistence.carts_repo import CartsRepo, CartConflict

logger = logging.getLogger("orchestrator.tools_v2.shipping")


def _cube_root_scale(dim_cm: float, total_qty: int) -> float:
    """Escala una dimensión por raíz cúbica del total — patrón existente
    en shipping_quote_tool original (multi-producto)."""
    if total_qty <= 1:
        return dim_cm
    return dim_cm * (total_qty ** (1.0 / 3.0))


async def handle_quote_shipping(
    *,
    ctx: ConversationContext,
    args: dict,
    supabase: Client,
    repo: CartsRepo,
) -> dict:
    """Cotiza envío usando los items reales del carrito persistido."""
    if not ctx.cart or not ctx.cart.is_open:
        return {"ok": False, "error": "no_open_cart"}
    if not ctx.cart.items:
        return {"ok": False, "error": "empty_cart"}

    city_text = str(args.get("city_text") or "").strip()
    if not city_text:
        return {"ok": False, "error": "city_text_required"}

    # 1. Resolver destino con DANE
    try:
        from tools.shipping_quote_tool import _resolve_destination_from_query
        dest, ambiguous = _resolve_destination_from_query(city_text)
    except Exception as exc:
        logger.exception("[shipping_tools.quote] DANE resolve failed")
        return {"ok": False, "error": f"dane_lookup_failed: {exc}"}

    if not dest:
        return {
            "ok": False,
            "error": "destination_not_found",
            "ambiguous_city": ambiguous,
            "message": f"No pude resolver '{city_text}' a una ciudad CO con DANE.",
        }

    # 2. Origen del tenant
    try:
        from tools.shipping_quote_tool import (
            _get_tenant_shipping_origin,
            _coerce_origin,
            _get_tenant_products_for_shipping_quote,
            DEFAULT_WEIGHT_KG,
            DEFAULT_LENGTH_CM,
            DEFAULT_WIDTH_CM,
            DEFAULT_HEIGHT_CM,
        )
        origin_cfg = _get_tenant_shipping_origin(supabase, ctx.tenant_id)
        origin = _coerce_origin(origin_cfg)
        if not origin:
            return {
                "ok": False,
                "error": "origin_not_configured",
                "message": "Origen del tenant sin DANE — Ajustes > Dirección.",
            }
    except Exception as exc:
        logger.exception("[shipping_tools.quote] origin lookup failed")
        return {"ok": False, "error": str(exc)}

    # 3. Construir paquete sumando ítems del carrito (peso + dimensiones).
    #    Lookup de pesos/dims por variation_id desde tabla product_variations.
    weight_kg = 0.0
    max_l = max_w = max_h = 0.0
    total_qty = 0
    summaries: list[str] = []

    products_for_shipping = _get_tenant_products_for_shipping_quote(supabase, ctx.tenant_id)
    var_index = {
        str(v.get("id")): (prod, v)
        for prod in products_for_shipping
        for v in (prod.get("product_variations") or [])
    }

    for item in ctx.cart.items:
        prod_var = var_index.get(item.variation_id)
        if prod_var:
            prod, var = prod_var
        else:
            prod, var = {}, {}
        w = float(var.get("weight_kg") or DEFAULT_WEIGHT_KG)
        l_cm = float(var.get("length_cm") or DEFAULT_LENGTH_CM)
        wd_cm = float(var.get("width_cm") or DEFAULT_WIDTH_CM)
        h_cm = float(var.get("height_cm") or DEFAULT_HEIGHT_CM)
        weight_kg += max(w, 0.05) * item.quantity
        max_l = max(max_l, l_cm)
        max_w = max(max_w, wd_cm)
        max_h = max(max_h, h_cm)
        total_qty += item.quantity

        title = str(prod.get("title") or "Producto")
        var_label = (
            ", ".join(f"{k}: {v}" for k, v in (var.get("attributes") or {}).items())
            or var.get("sku") or ""
        )
        summaries.append(
            f"{item.quantity}x {title} ({var_label})"
            if var_label else f"{item.quantity}x {title}"
        )

    package = {
        "weight_kg": round(max(weight_kg, 0.05), 3),
        "length_cm": round(_cube_root_scale(max_l, total_qty), 1),
        "width_cm": round(_cube_root_scale(max_w, total_qty), 1),
        "height_cm": round(_cube_root_scale(max_h, total_qty), 1),
    }

    # 4. Llamar Envia client (re-uso del existente, sin tocar)
    try:
        from integrations.envia_client import quote_shipment_sync  # type: ignore
    except Exception:
        # Path alternativo — algunos entornos lo importan diferente
        try:
            from services.envia_client import quote_shipment_sync  # type: ignore
        except Exception as exc:
            logger.exception("[shipping_tools.quote] envia client import failed")
            return {"ok": False, "error": "envia_client_unavailable"}

    try:
        rates = quote_shipment_sync(
            tenant_id=ctx.tenant_id,
            origin=origin,
            destination=dest,
            packages=[{
                "weight": package["weight_kg"],
                "length": package["length_cm"],
                "width": package["width_cm"],
                "height": package["height_cm"],
                "content": "Productos varios",
                "amount": ctx.cart.subtotal_cents / 100.0,
            }],
            supabase=supabase,
        )
    except Exception as exc:
        logger.exception("[shipping_tools.quote] envia call failed")
        return {"ok": False, "error": f"envia_failed: {exc}"}

    if not rates:
        return {"ok": False, "error": "no_rates_available"}

    cheapest = min(rates, key=lambda r: float(r.get("totalPrice") or r.get("total") or 0))
    fastest = min(rates, key=lambda r: int(r.get("deliveryEstimate") or r.get("days") or 99))

    # Persistir en cart.shipping_meta + shipping_cents.
    cheapest_cents = int(round(float(cheapest.get("totalPrice") or 0) * 100))
    shipping_meta = {
        "city": dest["city"],
        "state": dest["state"],
        "dane_code": dest["dane_code"],
        "rates": [
            {
                "carrier": str(r.get("carrier") or r.get("carrierService") or ""),
                "price_cents": int(round(float(r.get("totalPrice") or 0) * 100)),
                "delivery_days": int(r.get("deliveryEstimate") or r.get("days") or 0),
            }
            for r in rates
        ],
        "selected_carrier": None,
    }

    try:
        repo.update_shipping_meta(
            tenant_id=ctx.tenant_id,
            cart_id=ctx.cart.id,
            shipping_meta=shipping_meta,
            shipping_cents=cheapest_cents,  # default mínimo, cliente confirma luego
            expected_version=ctx.cart.version,
        )
    except CartConflict:
        return {"ok": False, "error": "concurrent_update", "retry": True}

    return {
        "ok": True,
        "destination": dest,
        "package": package,
        "products_summary": summaries,
        "cheapest": {
            "carrier": cheapest.get("carrier") or cheapest.get("carrierService"),
            "price_cents": cheapest_cents,
            "delivery_days": cheapest.get("deliveryEstimate") or cheapest.get("days"),
        },
        "fastest": {
            "carrier": fastest.get("carrier") or fastest.get("carrierService"),
            "price_cents": int(round(float(fastest.get("totalPrice") or 0) * 100)),
            "delivery_days": fastest.get("deliveryEstimate") or fastest.get("days"),
        },
    }


async def handle_select_carrier(
    *,
    ctx: ConversationContext,
    args: dict,
    repo: CartsRepo,
) -> dict:
    """Confirma elección de carrier; persiste en cart.shipping_meta.selected_carrier
    y actualiza shipping_cents al precio del seleccionado.
    """
    choice = str(args.get("carrier_choice") or "").strip().lower()
    if choice not in {"economica", "rapida"}:
        return {"ok": False, "error": "invalid_carrier_choice"}
    if not ctx.cart or not ctx.cart.is_open:
        return {"ok": False, "error": "no_open_cart"}

    sm = dict(ctx.cart.shipping_meta or {})
    rates = sm.get("rates") or []
    if not rates:
        return {"ok": False, "error": "no_quotes_to_choose_from"}

    if choice == "economica":
        chosen = min(rates, key=lambda r: int(r.get("price_cents") or 0))
    else:
        chosen = min(rates, key=lambda r: int(r.get("delivery_days") or 99))

    sm["selected_carrier"] = {
        "tag": choice,
        "carrier": chosen.get("carrier"),
        "price_cents": int(chosen.get("price_cents") or 0),
        "delivery_days": int(chosen.get("delivery_days") or 0),
    }

    try:
        repo.update_shipping_meta(
            tenant_id=ctx.tenant_id,
            cart_id=ctx.cart.id,
            shipping_meta=sm,
            shipping_cents=int(chosen.get("price_cents") or 0),
            expected_version=ctx.cart.version,
        )
    except CartConflict:
        return {"ok": False, "error": "concurrent_update", "retry": True}

    return {
        "ok": True,
        "selected": sm["selected_carrier"],
    }
