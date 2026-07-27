"""Adapter Wompi para generate_payment_link del agentic.

ADR-0011 lifecycle preservado (cart_as_SoT + idempotency + retry).
Valida invariantes pre-link Wompi (cart no vacío + shipping + PII).
Delega al endpoint interno del API service para reusar la lógica
canónica de create_order + create_link.
"""
from __future__ import annotations

from typing import Any

from tools.catalog_contract import variant_presentation  # ADR-0029 F5: extractor canónico único


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
    # Palanca 2 (gate determinístico): envío pendiente de recotizar = el cliente
    # agregó/quitó productos o cambió la dirección → la cotización vieja es inválida.
    # Error específico que guía al LLM (más claro que NO_SHIPPING). Refuerza el
    # chokepoint de pago contra cobrar envío incorrecto. (Convertido/abandonado ya
    # los bloquea el filtro status="open" de get_cart_with_items; dedup vive en la
    # idempotencia ADR-0011; COD-deshabilitado en carrier_capabilities.)
    if bool(cart.get("requires_requote")):
        return {
            "ok": False,
            "error": ("El envío cambió y debe recotizarse antes de pagar. "
                      "Llama quote_shipping con la dirección del cliente."),
            "code": "REQUOTE_PENDING",
        }
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
            .eq("tenant_id", tenant_id)
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

    # Y si el envío va a un TERCERO, sus datos también tienen que estar completos: en la
    # guía va SU nombre, SU celular y SU dirección, no los del titular de WhatsApp.
    #
    # Sin esto el pedido se creaba igual y la guía salía con lo que hubiera. En el
    # recorrido del 2026-07-27 el destinatario era {"name": "mi mama"} con todo lo demás
    # en null — un paquete que el courier no puede entregar.
    recipient = (cart.get("shipping_meta") or {}).get("recipient") or {}
    if any(recipient.get(k) for k in ("name", "phone", "address")):
        faltan_receptor = [
            f for f in ("name", "phone", "address") if not recipient.get(f)
        ]
        if faltan_receptor:
            return {
                "ok": False,
                "error": (
                    f"El envío va a un tercero y faltan sus datos: {faltan_receptor}. "
                    "Pídeselos al cliente y guárdalos con `set_shipping_recipient` "
                    "(NUNCA con save_contact_field, que pisaría al titular). En la guía "
                    "va el nombre de quien RECIBE."
                ),
                "code": "INCOMPLETE_RECIPIENT",
                "missing_fields": faltan_receptor,
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
        variant_label = variant_presentation(attrs) or None
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

    # Rev. 108 Fase B — COD bypass: si el cart tiene payment_method='cod',
    # `result.checkout_url` viene vacío INTENCIONAL (no hay link Wompi).
    # En ese caso, success se determina por `order_id` + `response_text`
    # presentes, no por checkout_url.
    cart_payment_method = (cart.get("payment_method") or "credit").lower()
    is_cod = cart_payment_method == "cod"

    has_order = bool(result and getattr(result, "order_id", None))
    has_url = bool(result and getattr(result, "checkout_url", None))

    # Rev. 108 fix arquitectónico — si stock insuficiente, el tool retornó
    # PaymentLinkResult con order_id="" + checkout_url="" + response_text
    # con la lista de SKUs faltantes. Propagamos ese mensaje al cliente
    # (NO ocultamos con COD_ORDER_FAILED / PAYMENT_LINK_UNAVAILABLE genérico).
    if result and not has_order and not has_url:
        rtxt = (getattr(result, "response_text", "") or "")
        if "stock" in rtxt.lower() or "sin stock" in rtxt.lower():
            return {
                "ok": False,
                "error": rtxt,
                "code": "INSUFFICIENT_STOCK",
                "direct_response": rtxt,
            }

    if not result or (not has_url and not is_cod):
        return {
            "ok": False,
            "error": "No se pudo generar el link de pago (Wompi/cart).",
            "code": "PAYMENT_LINK_UNAVAILABLE",
        }

    if is_cod and not has_order:
        return {
            "ok": False,
            "error": "Orden COD no pudo crearse.",
            "code": "COD_ORDER_FAILED",
        }

    return {
        "ok": True,
        "payment_method": cart_payment_method,
        "checkout_url": result.checkout_url,
        "order_id": getattr(result, "order_id", None),
        "amount_cents": int(getattr(result, "amount_in_cents", 0))
            or int(cart.get("total_cents") or 0),
        "expires_at": getattr(result, "expires_at", None),
        "message": getattr(result, "response_text", None),
    }
