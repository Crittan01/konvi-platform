"""Adapter Aveonline para quote_shipping del agentic.

ADR-0019 rev. 107 M.3. Provider alternativo a Envia (1 activo per-tenant,
sin fallback automático).

Convierte direcciones a formato Aveonline ('CITY(STATE)' uppercase),
invoca AveonlineClient, mapea QuoteOption → dict shape Envia-compatible
para que el LLM no vea diferencia.

Helper `to_aveonline_city_format` se re-exporta desde aquí para preservar
backward compat con código que importaba el alias underscore.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

# Re-export para backward compat con imports previos al refactor.
from integrations.aveonline_client import (  # noqa: F401
    to_aveonline_city_format as _to_aveonline_city_format,
)

logger = logging.getLogger(__name__)


async def quote_shipping_for_cart_aveonline(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    contact_id: Optional[str],
    city_query: str,
) -> dict:
    """Cotiza envío con AveonlineClient — espejo funcional del adapter Envia.

    Reusa helpers legacy de geo + package estimate, pero invoca el
    AveonlineClient en vez de Envia. El LLM ve mismo dict shape — la
    decisión de provider la toma `QuoteShippingTool` upstream según
    `tenant_shipping_provider_config.active_provider`.
    """
    from tools.shipping_quote_tool import (
        _resolve_destination_from_query,
        _get_tenant_shipping_origin,
        _estimate_package_from_cart_if_available,
        _coerce_origin,
        _coerce_destination,
    )
    from integrations.aveonline_client import (
        AveonlineClient,
        AveonlineAuthError,
        AveonlineNoCarriersError,
        AveonlinePackageLimitError,
        AveonlinePermanentError,
        AveonlineTransientError,
        to_aveonline_city_format,
    )

    # Resolver ciudad (reusa parser de legacy — devuelve city+state+dane).
    destination, _ = _resolve_destination_from_query(city_query)
    if not destination:
        return {
            "ok": False,
            "error": f"No reconozco la ciudad '{city_query}'. Indícame una ciudad de Colombia válida.",
            "code": "INVALID_CITY",
        }

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

    # Construir origin/destination en formato Aveonline (uppercase city+state).
    # Aveonline acepta `BOGOTA(CUNDINAMARCA)` uppercase o DANE 8-dig (§10.3).
    origin_aveonline_city = to_aveonline_city_format(
        origin.get("city") or "", origin.get("state") or "",
    )
    dest_aveonline_city = to_aveonline_city_format(
        destination.get("city") or "", destination.get("state") or "",
    )
    if not origin_aveonline_city or not dest_aveonline_city:
        return {
            "ok": False,
            "error": "No pude convertir origen/destino al formato Aveonline (falta city/state).",
            "code": "GEO_FORMAT_ERROR",
        }

    client = AveonlineClient(tenant_id, supabase)
    try:
        result = await client.quote(
            origin={
                "city_canonical": origin_aveonline_city,
                "city": origin.get("city"),
                "dane": origin.get("dane_code"),
            },
            destination={
                "city_canonical": dest_aveonline_city,
                "city": destination.get("city"),
                "dane": destination.get("dane_code"),
            },
            package={
                "weight_kg": float(getattr(package, "weight_kg", 1.0)),
                "length_cm": float(getattr(package, "length_cm", 10)),
                "width_cm": float(getattr(package, "width_cm", 10)),
                "height_cm": float(getattr(package, "height_cm", 10)),
                "declared_value_cop": int(getattr(package, "declared_value", 0) or 50000),
                "units": int(getattr(package, "quantity", 1) or 1),
                "product_name": str(getattr(package, "product_title", "Producto") or "Producto"),
                "cod_enabled": False,  # COD se activa más adelante en flujo (M.x)
            },
        )
    except AveonlineAuthError as exc:
        return {
            "ok": False,
            "error": (
                "Las credenciales de Aveonline no son válidas. Reconecta la "
                "integración en Settings → Despachos."
            ),
            "code": "AVEONLINE_AUTH",
            "exc": str(exc),
        }
    except AveonlineNoCarriersError:
        return {
            "ok": False,
            "error": (
                f"Aveonline no tiene transportadoras disponibles para envío a "
                f"{destination.get('city')}. Inténtalo más tarde o pide un especialista."
            ),
            "code": "AVEONLINE_NO_CARRIERS",
        }
    except AveonlinePackageLimitError:
        return {
            "ok": False,
            "error": (
                "El paquete excede el peso o dimensiones máximas de los carriers "
                "Aveonline. Divídelo o consulta a un especialista."
            ),
            "code": "AVEONLINE_PACKAGE_LIMIT",
        }
    except AveonlineTransientError as exc:
        logger.warning("[agentic.shipping.aveonline] transient: %s", exc)
        return {
            "ok": False,
            "error": (
                "Aveonline está tardando en responder. Te pido reintentar en "
                "un momento."
            ),
            "code": "AVEONLINE_TRANSIENT",
        }
    except AveonlinePermanentError as exc:
        logger.error("[agentic.shipping.aveonline] permanent: %s", exc)
        return {
            "ok": False,
            "error": f"Aveonline rechazó la solicitud: {exc}",
            "code": "AVEONLINE_PERMANENT",
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("[agentic.shipping.aveonline] unexpected: %s", exc, exc_info=True)
        return {
            "ok": False,
            "error": "Error inesperado cotizando con Aveonline.",
            "code": "AVEONLINE_UNEXPECTED",
        }

    # Mapear QuoteOption[] → dict shape Envia-compatible.
    options: list[dict] = []
    for opt in result.options:
        options.append({
            "rate_id": opt.rate_id,
            "carrier": opt.carrier_name,
            "service_level": opt.service_level,
            "price_cents": opt.price_cents,
            "eta_date": f"{opt.eta_days}d" if opt.eta_days else "",
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
            "[agentic.shipping.aveonline] persist quoted_options falló: %s", exc,
        )

    return {
        "ok": True,
        "options": options,
        "city_normalized": destination.get("city"),
        "destination": destination,
        "provider": "aveonline",  # marker para audit
    }
