"""Registry de handlers — mapping nombre del tool → callable.

Usado por el coordinator para dispatching dinámico de los function_calls
emitidos por el LLM.

Cada handler tiene la firma::

    async def handler(*, ctx: ConversationContext, args: dict, **deps) -> dict

donde ``deps`` puede incluir ``supabase``, ``repo``, etc. — el coordinator
los inyecta según corresponda.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from tools_v2 import cart_tools, catalog_tools, customer_tools, order_tools, shipping_tools


# Mapping nombre del tool → handler async. Mantener alineado con
# llm.tool_specs.ALL_TOOLS y core.fsm.ALLOWED_TOOLS_BY_STATE.
HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    # Catalog & KB
    "search_catalog": catalog_tools.handle_search_catalog,
    "get_product_image": catalog_tools.handle_get_product_image,
    "answer_kb": catalog_tools.handle_answer_kb,
    # Cart
    "add_item_to_cart": cart_tools.handle_add_item_to_cart,
    "remove_item_from_cart": cart_tools.handle_remove_item_from_cart,
    # Shipping
    "quote_shipping": shipping_tools.handle_quote_shipping,
    "select_carrier": shipping_tools.handle_select_carrier,
    # Customer data
    "record_consent": customer_tools.handle_record_consent,
    "set_customer_email": customer_tools.handle_set_customer_email,
    "set_customer_name": customer_tools.handle_set_customer_name,
    "set_customer_document": customer_tools.handle_set_customer_document,
    "set_customer_address": customer_tools.handle_set_customer_address,
    # Order lifecycle
    "render_summary": order_tools.handle_render_summary,
    "confirm_order": order_tools.handle_confirm_order,
    "cancel_order": order_tools.handle_cancel_order,
    "escalate_to_human": order_tools.handle_escalate_to_human,
}


def get_handler(tool_name: str) -> Callable[..., Awaitable[dict]] | None:
    """Devuelve el handler registrado para ``tool_name``, o None si no existe."""
    return HANDLERS.get(tool_name)


def all_tool_names() -> frozenset[str]:
    """Conjunto inmutable de tools registrados — útil para validar contra FSM."""
    return frozenset(HANDLERS.keys())
