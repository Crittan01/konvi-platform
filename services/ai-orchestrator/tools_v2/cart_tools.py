"""Handlers de tools de carrito.

Tools cubiertos:
  - ``add_item_to_cart``      → CartsRepo.add_item (vía RPC atómico)
  - ``remove_item_from_cart`` → CartsRepo.remove_item

Reglas de uso (alineadas con :mod:`llm.tool_specs`):
  - El LLM SIEMPRE pasa ``variation_id`` (no se permite ambiguar a producto).
  - Si el cliente pide 2 variantes del mismo producto, el LLM emite 2 calls
    (una por variation_id) — el upsert idempotente del repo las suma.
"""
from __future__ import annotations

import logging
from typing import Any

from core.context import ConversationContext
from core.exceptions import ToolExecutionError
from persistence.carts_repo import (
    CartsRepo,
    CartConflict,
    CartNotFound,
    CartClosed,
)

logger = logging.getLogger("orchestrator.tools_v2.cart")


def _resolve_unit_price_cents(catalog: list[dict], variation_id: str) -> int:
    """Encuentra el precio actual de una variante en el catálogo del tenant.

    El precio se "congela" en el cart_item al momento de agregar — si después
    cambia el catálogo, el cliente paga lo que vio cuando agregó.
    """
    for prod in catalog or []:
        for var in prod.get("variants") or []:
            if str(var.get("id")) == str(variation_id):
                price = var.get("price")
                if price is None:
                    continue
                # Catálogo expone precio en pesos; convertimos a centavos
                return int(round(float(price) * 100))
    raise ValueError(f"variation_id={variation_id} no encontrada en catálogo")


def _resolve_product_id(catalog: list[dict], variation_id: str) -> str:
    for prod in catalog or []:
        for var in prod.get("variants") or []:
            if str(var.get("id")) == str(variation_id):
                return str(prod["id"])
    raise ValueError(f"variation_id={variation_id} sin product_id en catálogo")


async def handle_add_item_to_cart(
    *,
    ctx: ConversationContext,
    args: dict,
    repo: CartsRepo,
) -> dict:
    """Agrega (o incrementa) un item del carrito.

    Args esperados (ver llm.tool_specs.ADD_ITEM_TO_CART):
      - ``product_id`` (str)
      - ``variation_id`` (str)
      - ``quantity`` (int, default 1)

    Returns dict serializable que se envía al LLM como function_response.
    """
    variation_id = str(args.get("variation_id") or "").strip()
    raw_qty = args.get("quantity")
    quantity = int(raw_qty) if raw_qty is not None else 1
    if not variation_id:
        return {"ok": False, "error": "variation_id obligatorio"}
    if quantity < 1:
        return {"ok": False, "error": "quantity debe ser >= 1"}

    # product_id puede venir del LLM, pero lo verificamos contra catálogo
    # (no confiamos en el LLM como fuente de verdad — regla del repo).
    try:
        product_id = _resolve_product_id(ctx.catalog, variation_id)
        unit_price_cents = _resolve_unit_price_cents(ctx.catalog, variation_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Asegurar que existe carrito open. Si no, crearlo.
    cart = ctx.cart
    if cart is None:
        cart = repo.create_open_cart(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            contact_id=ctx.contact_id,
        )

    try:
        result = repo.add_item(
            tenant_id=ctx.tenant_id,
            cart_id=cart.id,
            product_id=product_id,
            variation_id=variation_id,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            expected_version=None,  # tolerante: dejamos que el RPC tome el current
        )
        logger.info(
            "[cart_tools.add] cart=%s var=%s qty=%d v→%s",
            cart.id, variation_id, quantity, result.get("new_version"),
        )
        return {
            "ok": True,
            "cart_id": result["cart_id"],
            "version": result["new_version"],
            "subtotal_cents": result["subtotal_cents"],
            "total_cents": result["total_cents"],
        }
    except CartConflict as exc:
        logger.warning("[cart_tools.add] conflict — caller debería reintentar: %s", exc)
        return {"ok": False, "error": "concurrent_update", "retry": True}
    except (CartNotFound, CartClosed) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("[cart_tools.add] failed")
        raise ToolExecutionError("add_item_to_cart", exc) from exc


async def handle_remove_item_from_cart(
    *,
    ctx: ConversationContext,
    args: dict,
    repo: CartsRepo,
) -> dict:
    variation_id = str(args.get("variation_id") or "").strip()
    if not variation_id:
        return {"ok": False, "error": "variation_id obligatorio"}

    cart = ctx.cart
    if cart is None or not cart.is_open:
        return {"ok": False, "error": "no hay carrito open"}

    try:
        new_v = repo.remove_item(
            tenant_id=ctx.tenant_id,
            cart_id=cart.id,
            variation_id=variation_id,
            expected_version=cart.version,
        )
        logger.info(
            "[cart_tools.remove] cart=%s var=%s v→%s",
            cart.id, variation_id, new_v,
        )
        return {"ok": True, "version": new_v}
    except CartConflict:
        return {"ok": False, "error": "concurrent_update", "retry": True}
    except Exception as exc:
        logger.exception("[cart_tools.remove] failed")
        raise ToolExecutionError("remove_item_from_cart", exc) from exc
