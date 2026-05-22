"""Adapters legacy → agentic tools.

ADR-0018. Cada función aquí es una **interfaz tool-friendly** que invoca
helpers internos de los módulos legacy (`shipping_quote_tool.py`,
`payment_link_tool.py`, `cart_tool.py`). Production-grade:

  • NO modifica los módulos legacy (preserva shadow mode + cutover).
  • Devuelve estructuras dict/JSON que el LLM puede leer.
  • Maneja errores explícitamente — nunca raise; siempre dict con `ok`+detalle.

El propósito es que `agentic/tools/*.py` tenga interfaces declarativas
(Pydantic schemas) y delegue la lógica de negocio a estos adapters.
Cuando completemos cutover (Fase 3), estos adapters pueden absorberse
en módulos `agentic/services/` permanentes; mientras tanto, sirven como
puente sin duplicar lógica de Wompi/Envia.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Shipping quote ────────────────────────────────────────────────────────


async def quote_shipping_for_cart(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    contact_id: Optional[str],
    city_query: str,
) -> dict:
    """Cotiza envío para el cart actual a la ciudad dada.

    Returns:
        dict:
          • ok (bool)
          • options (list): [{rate_id, carrier, service_level, price_cents, eta_date}, ...]
          • city_normalized (str)
          • error (str opcional)
          • code (str opcional)
    """
    from tools.shipping_quote_tool import (
        _resolve_destination_from_query,
        _get_tenant_shipping_origin,
        _estimate_package_from_cart_if_available,
        _build_quote_payload,
        _request_shipping_quote,
        _coerce_origin,
        _coerce_destination,
    )

    # Resolver ciudad → destination canónico (con DANE code).
    destination, _ = _resolve_destination_from_query(city_query)
    if not destination:
        return {
            "ok": False,
            "error": f"No reconozco la ciudad '{city_query}'. Indícame una ciudad de Colombia válida.",
            "code": "INVALID_CITY",
        }

    # Origin del tenant.
    origin = _get_tenant_shipping_origin(supabase, tenant_id)
    if not origin:
        return {
            "ok": False,
            "error": "Origen de envío no configurado para el tenant.",
            "code": "NO_ORIGIN_CONFIG",
        }
    origin = _coerce_origin(origin)
    destination = _coerce_destination(destination)
    if not origin or not destination:
        return {
            "ok": False,
            "error": "Origen o destino malformados.",
            "code": "INVALID_GEO",
        }

    # Estimar paquete desde el cart.
    # `_estimate_package_from_cart_if_available` retorna PackageEstimateDecision
    # con .package (Optional[PackageEstimate]) — NO el PackageEstimate directo.
    # Argumentos en orden positional: (supabase, tenant_id, conversation_id).
    package_decision = _estimate_package_from_cart_if_available(
        supabase, tenant_id, conversation_id,
    )
    package = package_decision.package if package_decision else None
    if not package:
        ambiguous = (
            package_decision.ambiguous_product_titles
            if package_decision else []
        )
        if ambiguous:
            return {
                "ok": False,
                "error": (
                    f"No pude resolver dimensiones para: "
                    f"{', '.join(ambiguous[:3])}. Confirma productos exactos."
                ),
                "code": "AMBIGUOUS_PRODUCTS",
            }
        return {
            "ok": False,
            "error": "No pude estimar el paquete (cart vacío o productos sin dimensiones).",
            "code": "NO_PACKAGE_ESTIMATE",
        }

    # Construir payload + invocar Envia.
    payload = _build_quote_payload(origin, destination, package)
    try:
        status_code, response = await _request_shipping_quote(tenant_id, payload)
    except Exception as exc:
        logger.warning("[agentic.shipping] envia call falló: %s", exc)
        return {"ok": False, "error": f"Envia falló: {exc}", "code": "ENVIA_ERROR"}

    if status_code != 200 or not response.get("data"):
        return {
            "ok": False,
            "error": "Envia no devolvió opciones válidas.",
            "code": "ENVIA_NO_OPTIONS",
        }

    # Parsear opciones — formato Envia.
    options: list[dict] = []
    for rate in response["data"]:
        price = rate.get("totalPrice")
        if price is None:
            continue
        options.append({
            "rate_id": str(rate.get("uuid") or rate.get("id") or ""),
            "carrier": str(rate.get("carrier") or ""),
            "service_level": str(rate.get("service") or ""),
            "price_cents": int(float(price) * 100),
            "eta_date": str(rate.get("deliveryEstimate") or ""),
        })

    if not options:
        return {
            "ok": False,
            "error": f"No hay carriers disponibles para envío a '{destination.get('city')}'.",
            "code": "NO_CARRIERS",
        }

    # Persistir quoted_options en DB (fix RATE_ID_NOT_CACHED — DB-first
    # Plan A.0.2). El cart_id se resuelve desde conversation_id+tenant_id.
    try:
        from tools.cart_tool import get_cart_with_items, set_quoted_options
        cart_row = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
        if cart_row and cart_row.get("id"):
            set_quoted_options(
                supabase,
                cart_id=cart_row["id"],
                tenant_id=tenant_id,
                options=options,
            )
    except Exception as exc:
        # Fallo persistencia NO bloquea cotización al cliente — el LLM
        # puede mostrar opciones; si select_carrier falla por not-cached,
        # se cotizará de nuevo. Pero loggear para visibility.
        logger.warning(
            "[agentic.shipping] persist quoted_options falló: %s", exc,
        )

    return {
        "ok": True,
        "options": options,
        "city_normalized": destination.get("city"),
        "destination": destination,
    }


# ─── Select carrier ────────────────────────────────────────────────────────


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
        Necesario para guardar carrier + price + eta sin reconsultar Envia.

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


# ─── Payment link ──────────────────────────────────────────────────────────


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

    # Delegar al payment_link_tool legacy mediante invocación directa
    # de su API interna (create_payment_link_sync).
    from integrations.wompi_client import create_payment_link_sync

    auth_token = _build_api_auth_token(tenant_id)
    if not auth_token:
        return {
            "ok": False, "error": "No pude obtener auth token.",
            "code": "AUTH_ERROR",
        }

    # Construir payload Wompi desde cart + contact (similar a payment_link_tool).
    # Para simplicidad y NO duplicar lógica compleja, delegamos a la
    # función existente que ya hace todo (create_order + create_link).
    # Esa función está en payment_link_tool.handle_payment_link_if_applicable
    # pero usa flow conversacional. Aquí usamos invocación directa via
    # endpoint interno del api.
    try:
        # Importar y llamar al endpoint interno (orders/create_payment_link)
        # del API service. Esta es la API auténtica que payment_link_tool
        # usa internamente — la invocamos directo desde el adapter.
        import httpx
        import os
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
