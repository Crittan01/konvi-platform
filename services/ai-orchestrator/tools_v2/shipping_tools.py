"""Handlers de tools de envío.

Tools cubiertos:
  - ``quote_shipping``  → cotiza con Envia desde el carrito persistido (NO
    re-deriva del history). Persiste rates + costo en
    ``conversation_carts.shipping_meta`` + ``shipping_cents``.
  - ``select_carrier``  → confirma elección entre Económica/Rápida.

Diferencia fundamental con la versión vieja:
  - Lee ``ctx.cart.items`` como fuente de verdad. El paquete se calcula
    sumando peso y dimensiones de las variantes reales del carrito.
  - NO hay regex sobre el historial. NO hay falsos positivos por apellidos
    que coincidan con ciudad.

Llama el endpoint ``/api/v1/shipping/quote`` del API gateway (que tiene
acceso al Vault con credenciales Envia por tenant). El orquestador NO
importa ``envia_client`` directamente — esa dependencia vive en el API.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

import httpx
import jwt
from supabase import Client

from core.context import ConversationContext
from persistence.carts_repo import CartsRepo, CartConflict

logger = logging.getLogger("orchestrator.tools_v2.shipping")


API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SHIPPING_REQUEST_TIMEOUT_SECONDS = int(os.getenv("SHIPPING_REQUEST_TIMEOUT_SECONDS", "20"))


def _build_api_auth_token(tenant_id: str) -> Optional[str]:
    """Construye un JWT compatible con el middleware del API gateway.

    Replica el patrón de ``shipping_quote_tool._build_api_auth_token`` y
    ``payment_link_tool._build_api_auth_token`` para mantener una sola
    convención de auth interno.
    """
    if not SUPABASE_JWT_SECRET:
        return None
    import time
    now = int(time.time())
    payload = {
        "aud": "authenticated",
        "sub": "orchestrator",
        "role": "authenticated",
        "email": "orchestrator@system.local",
        "iat": now,
        "exp": now + 300,
        "app_metadata": {"tenant_id": tenant_id, "role": "owner"},
        "user_metadata": {},
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def _cube_root_scale(dim_cm: float, total_qty: int) -> float:
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

    # 3. Construir paquete sumando ítems del carrito.
    products_for_shipping = _get_tenant_products_for_shipping_quote(supabase, ctx.tenant_id)
    var_index: dict[str, tuple[dict, dict]] = {}
    for prod in products_for_shipping:
        for v in (prod.get("product_variations") or []):
            var_index[str(v.get("id"))] = (prod, v)

    weight_kg = 0.0
    max_l = max_w = max_h = 0.0
    total_qty = 0
    summaries: list[str] = []

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
        var_label = ", ".join(
            f"{k}: {v}" for k, v in (var.get("attributes") or {}).items()
        ) or var.get("sku") or ""
        summaries.append(
            f"{item.quantity}x {title} ({var_label})" if var_label
            else f"{item.quantity}x {title}"
        )

    package = {
        "weight": round(max(weight_kg, 0.05), 3),
        "length": round(max(_cube_root_scale(max_l, total_qty), 1.0), 1),
        "width": round(max(_cube_root_scale(max_w, total_qty), 1.0), 1),
        "height": round(max(_cube_root_scale(max_h, total_qty), 1.0), 1),
        "amount": max(total_qty, 1),
        "content": " + ".join(summaries[:3])[:120] or "Mercancía general",
        "insuranceAmount": 0,
    }

    # 4. POST /api/v1/shipping/quote (API gateway con Vault).
    token = _build_api_auth_token(ctx.tenant_id)
    if not token:
        return {"ok": False, "error": "auth_token_unavailable"}

    payload = {
        "origin": origin,
        "destination": dest,
        "parcels": [package],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"v2-quote-{uuid.uuid4()}",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(SHIPPING_REQUEST_TIMEOUT_SECONDS),
        ) as client:
            resp = await client.post(
                f"{API_URL}/api/v1/shipping/quote",
                json=payload, headers=headers,
            )
            body = resp.json() if resp.content else {}
    except Exception as exc:
        logger.exception("[shipping_tools.quote] HTTP call failed")
        return {"ok": False, "error": f"shipping_api_failed: {exc}"}

    if resp.status_code not in (200, 201):
        detail = (body or {}).get("detail", "")
        logger.warning(
            "[shipping_tools.quote] API respondió %s: %s",
            resp.status_code, detail,
        )
        return {
            "ok": False,
            "error": "shipping_api_error",
            "status_code": resp.status_code,
            "detail": detail,
        }

    highlights = (body or {}).get("highlights") or {}
    rates_raw = (body or {}).get("rates") or []
    cheapest = highlights.get("cheapest")
    fastest = highlights.get("fastest")

    if not cheapest and not fastest:
        return {
            "ok": False,
            "error": "no_rates_returned",
            "message": "No hay opciones de envío disponibles para este destino.",
        }

    # API gateway responde en snake_case: total_price, delivery_estimate.
    # El campo carrier viene como string en `carrier`/`carrierDescription`
    # según el camino del normalizador. Ref:
    # services/api/routers/shipping.py:577-591
    def _price_cents(rate: dict) -> int:
        v = (
            rate.get("total_price")
            or rate.get("totalPrice")
            or rate.get("total")
            or rate.get("price")
            or 0
        )
        return int(round(float(v) * 100))

    def _delivery_days(rate: dict) -> int:
        """Extrae días estimados. La API puede devolver un int (ej. 2),
        un string formato '2-6 días' o el string 'mañana'/'hoy'.
        Usamos el límite inferior del rango como conservador.
        """
        raw = (
            rate.get("delivery_estimate")
            or rate.get("deliveryEstimate")
            or rate.get("days")
            or 0
        )
        if isinstance(raw, (int, float)):
            return int(raw)
        import re as _re
        m = _re.search(r"\d+", str(raw))
        return int(m.group(0)) if m else 0

    cheapest_cents = _price_cents(cheapest) if cheapest else 0

    # Persistir rates en cart.shipping_meta
    shipping_meta = {
        "city": dest.get("city"),
        "state": dest.get("state"),
        "dane_code": dest.get("dane_code"),
        "rates": [
            {
                "carrier": str(r.get("carrier") or r.get("carrierService") or ""),
                "price_cents": _price_cents(r),
                "delivery_days": _delivery_days(r),
                "tag": r.get("tag"),
            }
            for r in rates_raw[:6]
        ],
        "selected_carrier": None,
    }

    try:
        repo.update_shipping_meta(
            tenant_id=ctx.tenant_id,
            cart_id=ctx.cart.id,
            shipping_meta=shipping_meta,
            shipping_cents=cheapest_cents,
            expected_version=None,  # read-current dentro del repo
        )
    except CartConflict:
        return {"ok": False, "error": "concurrent_update", "retry": True}

    return {
        "ok": True,
        "destination": {
            "city": dest.get("city"),
            "state": dest.get("state"),
            "dane_code": dest.get("dane_code"),
        },
        "products_summary": summaries,
        "cheapest": {
            "carrier": cheapest.get("carrier") or cheapest.get("carrierService"),
            "price_cents": cheapest_cents,
            "delivery_days": _delivery_days(cheapest),
        } if cheapest else None,
        "fastest": {
            "carrier": fastest.get("carrier") or fastest.get("carrierService"),
            "price_cents": _price_cents(fastest),
            "delivery_days": _delivery_days(fastest),
        } if fastest else None,
    }


async def handle_select_carrier(
    *,
    ctx: ConversationContext,
    args: dict,
    repo: CartsRepo,
) -> dict:
    """Confirma elección de carrier; persiste en cart.shipping_meta.selected_carrier."""
    raw_choice = str(args.get("carrier_choice") or "").strip().lower()
    # Normalizar acentos: el LLM puede emitir 'rápida' o 'rapida'.
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", raw_choice)
    choice = "".join(c for c in nfkd if not unicodedata.combining(c))
    if choice not in {"economica", "rapida"}:
        logger.warning(
            "[shipping_tools.select] choice inválido raw=%r normalized=%r",
            raw_choice, choice,
        )
        return {"ok": False, "error": "invalid_carrier_choice"}
    if not ctx.cart or not ctx.cart.is_open:
        return {"ok": False, "error": "no_open_cart"}

    sm = dict(ctx.cart.shipping_meta or {})
    rates = sm.get("rates") or []
    if not rates:
        return {"ok": False, "error": "no_quotes_to_choose_from"}

    if choice == "economica":
        chosen = min(rates, key=lambda r: int(r.get("price_cents") or 0))
    else:  # rapida
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
            expected_version=None,  # read-current dentro del repo
        )
    except CartConflict:
        return {"ok": False, "error": "concurrent_update", "retry": True}

    return {"ok": True, "selected": sm["selected_carrier"]}
