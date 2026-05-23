"""Adapter Wompi para generate_payment_link del agentic.

ADR-0011 lifecycle preservado (cart_as_SoT + idempotency + retry).
Valida invariantes pre-link Wompi (cart no vacío + shipping + PII).
Delega al endpoint interno del API service para reusar la lógica
canónica de create_order + create_link.
"""
from __future__ import annotations

import os
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
    from tools.payment_link_tool import _build_api_auth_token

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

    auth_token = _build_api_auth_token(tenant_id)
    if not auth_token:
        return {
            "ok": False, "error": "No pude obtener auth token.",
            "code": "AUTH_ERROR",
        }

    # Delegar al endpoint interno del API service que ya tiene la lógica
    # canónica de create_order + create_payment_link (ADR-0011 §6.1-§6.4.4).
    try:
        import httpx
        api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{api_base}/api/v1/orders/create_payment_link",
                json={
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "contact_id": contact_id,
                },
                headers={"Authorization": f"Bearer {auth_token}"},
                timeout=30.0,
            )
        if response.status_code != 200:
            return {
                "ok": False,
                "error": f"API error {response.status_code}: {response.text[:200]}",
                "code": "PAYMENT_API_ERROR",
            }
        data = response.json()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error generando link: {exc}",
            "code": "PAYMENT_ERROR",
        }

    return {
        "ok": True,
        "checkout_url": data.get("checkout_url"),
        "order_id": data.get("order_id"),
        "order_code": data.get("order_code"),
        "amount_cents": data.get("amount_in_cents"),
    }
