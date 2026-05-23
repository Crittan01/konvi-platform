"""Adapter Envia para quote_shipping del agentic.

ADR-0018 + plan rev. 105 H.2. Reusa helpers internos del legacy
`tools/shipping_quote_tool.py` (preserva shadow mode + cutover).

NO modifica el legacy. Devuelve dict normalizado provider-agnostic
para que el LLM no vea diferencia entre Envia y Aveonline.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def quote_shipping_for_cart(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    contact_id: Optional[str],
    city_query: str,
) -> dict:
    """Cotiza envío para el cart actual a la ciudad dada vía Envia.

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

    # Estimar paquete desde el cart. `_estimate_package_from_cart_if_available`
    # retorna PackageEstimateDecision con .package (Optional[PackageEstimate]).
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
        logger.warning("[agentic.shipping.envia] envia call falló: %s", exc)
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

    # Persistir quoted_options en DB (DB-first Plan A.0.2).
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
        logger.warning(
            "[agentic.shipping.envia] persist quoted_options falló: %s", exc,
        )

    return {
        "ok": True,
        "options": options,
        "city_normalized": destination.get("city"),
        "destination": destination,
    }
