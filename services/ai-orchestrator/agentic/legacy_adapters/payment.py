"""Adapter Wompi para generate_payment_link del agentic.

ADR-0011 lifecycle preservado (cart_as_SoT + idempotency + retry).
Valida invariantes pre-link Wompi (cart no vacío + shipping + PII).
Delega al endpoint interno del API service para reusar la lógica
canónica de create_order + create_link.
"""
from __future__ import annotations

from typing import Any


async def generate_payment_link_for_cart(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    contact_id: str,
) -> dict:
    """Genera link de pago Wompi para el cart actual.

    Production-grade: valida invariantes Wompi (ADR-0011) antes de
    invocar la API:
      • Cart no vacío.
      • Shipping cotizado + carrier seleccionado.
      • PII completa (consent + email + name + doc + direction).

    Returns:
      dict con ok + checkout_url + order_id + amount_cents (success),
      o ok=False + error + code (failure con razón explícita).
    """
    from tools.cart_tool import get_cart_with_items

    cart = get_cart_with_items(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
    )
    if not cart or not (cart.get("items") or []):
        return {"ok": False, "error": "Cart vacío.", "code": "EMPTY_CART"}
    if int(cart.get("shipping_cents") or 0) <= 0:
        return {
            "ok": False,
            "error": "Falta cotizar envío. Llama quote_shipping + select_carrier.",
            "code": "NO_SHIPPING",
        }
    if not contact_id:
        return {"ok": False, "error": "No hay contact_id.", "code": "NO_CONTACT"}

    # Verificar PII completa.
    try:
        res = (
            supabase.table("contacts")
            .select("consent_given, email, name, document_type, document_number, address")
            .eq("id", contact_id)
            .single()
            .execute()
        )
        contact = res.data or {}
    except Exception as exc:
        return {
            "ok": False, "error": f"Error leyendo contacto: {exc}",
            "code": "CONTACT_READ_ERROR",
        }
    missing = [
        f for f in ("consent_given", "email", "name", "document_type",
                    "document_number", "address")
        if not contact.get(f)
    ]
    if missing:
        return {
            "ok": False,
            "error": f"Faltan campos PII: {missing}. Pide al cliente.",
            "code": "INCOMPLETE_PII",
            "missing_fields": missing,
        }

    # Rev. 107: refactor — invocar in-process la función canónica
    # `handle_payment_link_if_applicable` del legacy (mismo runtime
    # ai-orchestrator). Evita el round-trip HTTP a la API y reusa toda
    # la lógica (idempotencia + retry Wompi + cart_events emit). El
    # endpoint REST `POST /api/v1/orders/create_payment_link` que el
    # adapter llamaba originalmente NO existe — el path real es 2-pasos
    # `POST /api/v1/orders/` + `POST /{id}/payment-link`. Llamar directo
    # a la función Python evita re-implementar ese protocolo en HTTP.
    # Rev. 107: construir verified_ctx con items detallados del cart
    # para que `handle_payment_link_if_applicable` persista order_items
    # reales (title + variation_id + unit_price). Sin esto cae al fallback
    # genérico "Pedido vía WhatsApp" qty=1, perdiendo el desglose por
    # variante (bug runtime detectado conducción KAIU — `get_recent_orders`
    # devolvía un solo item placeholder en lugar de los 4 reales).
    verified_items: list[dict] = []
    for it in (cart.get("items") or []):
        prod = it.get("product") or {}
        var = it.get("variation") or {}
        title = prod.get("title") or prod.get("name") or "Producto"
        # variant_label desde attributes (matching naming KAIU: Presentación/Volumen).
        attrs = var.get("attributes") or {}
        variant_label = None
        for k in ("Presentación", "presentacion", "size", "Volumen", "volumen", "label"):
            if k in attrs and attrs[k]:
                variant_label = str(attrs[k])
                break
        verified_items.append({
            "title": title,
            "variant_label": variant_label,
            "quantity": int(it.get("quantity") or 1),
            "unit_price_cents": int(it.get("unit_price_cents") or 0),
            "product_id": it.get("product_id"),
            "variation_id": it.get("variation_id"),
        })

    try:
        from tools.payment_link_tool import handle_payment_link_if_applicable
        result = await handle_payment_link_if_applicable(
            tenant_id=tenant_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            contact_name=contact.get("name"),
            total_in_cents=int(cart.get("total_cents") or 0),
            shipping_cost_cents=int(cart.get("shipping_cents") or 0),
            notes=None,
            supabase=supabase,
            verified_ctx={"items": verified_items} if verified_items else None,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error generando link: {exc}",
            "code": "PAYMENT_ERROR",
        }

    if not result or not getattr(result, "checkout_url", None):
        return {
            "ok": False,
            "error": "No se pudo generar el link de pago (Wompi/cart).",
            "code": "PAYMENT_LINK_UNAVAILABLE",
        }

    return {
        "ok": True,
        "checkout_url": result.checkout_url,
        "order_id": getattr(result, "order_id", None),
        "amount_cents": int(getattr(result, "amount_in_cents", 0))
            or int(cart.get("total_cents") or 0),
        "expires_at": getattr(result, "expires_at", None),
        "message": getattr(result, "response_text", None),
    }
