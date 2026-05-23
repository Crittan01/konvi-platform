"""Adapters provider-agnostic relacionados con el cart.

`select_carrier_for_cart` recibe rate_data ya resuelto (por el caller que
invocó quote_shipping_for_cart o quote_shipping_for_cart_aveonline). Solo
persiste la elección en cart.shipping_meta — no consulta Envia ni Aveonline.
"""
from __future__ import annotations

from typing import Any


async def select_carrier_for_cart(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    rate_id: str,
    rate_data: dict,
) -> dict:
    """Persiste la elección de carrier en cart.shipping_meta.

    Args:
      rate_data: el dict del rate elegido (de quote_shipping options).
        Necesario para guardar carrier + price + eta sin reconsultar provider.

    Returns:
      dict con ok + carrier + service_level + shipping_cents + total_cents.
    """
    from tools.cart_tool import get_cart_with_items, set_shipping_meta

    cart = get_cart_with_items(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
    )
    if not cart:
        return {"ok": False, "error": "No hay cart activo.", "code": "NO_CART"}

    try:
        set_shipping_meta(
            supabase,
            cart_id=cart["id"],
            tenant_id=tenant_id,
            carrier=str(rate_data.get("carrier") or ""),
            service_level=str(rate_data.get("service_level") or ""),
            rate_id=rate_id,
            shipping_cents=int(rate_data.get("price_cents") or 0),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error guardando shipping en cart: {exc}",
            "code": "CART_WRITE_ERROR",
        }

    subtotal_cents = int(cart.get("subtotal_cents") or 0)
    shipping_cents = int(rate_data.get("price_cents") or 0)
    return {
        "ok": True,
        "carrier": rate_data.get("carrier"),
        "service_level": rate_data.get("service_level"),
        "shipping_cents": shipping_cents,
        "total_cents": subtotal_cents + shipping_cents,
    }
