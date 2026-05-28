"""Mapeo estado → tools permitidos (rev. 109 Día 2).

Reduce carga cognitiva del LLM: en lugar de 15 tools registradas, cada
estado expone solo las 3-6 relevantes para su contexto.

Tools globales registradas (15 post-consolidación rev. 108):
  list_catalog, get_cart, add_to_cart, update_cart_item_quantity,
  remove_cart_item, get_contact_info, record_consent, save_contact_field,
  quote_shipping, select_carrier, generate_payment_link, escalate_to_human,
  get_recent_orders, kb_query, send_product_image
"""
from __future__ import annotations

from agentic.state_machine.states import AgenticState


# Tools comunes a múltiples estados (escalation siempre permitido).
_ESCALATE = "escalate_to_human"

# Mapeo declarativo estado → set de tool names permitidos.
# El orden de los nombres NO importa (set), pero por convención listamos
# primero el tool "principal" del estado.
_TOOLS_BY_STATE: dict[AgenticState, frozenset[str]] = {
    # Saludo + presentación inicial — cliente puede preguntar pedido previo.
    AgenticState.GREETING: frozenset({
        "list_catalog",
        "get_contact_info",
        "get_recent_orders",
        "kb_query",
        "send_product_image",
        _ESCALATE,
    }),
    # Navegación catálogo, antes de empezar cart.
    AgenticState.EXPLORING: frozenset({
        "list_catalog",
        "send_product_image",
        "kb_query",
        "get_contact_info",
        _ESCALATE,
    }),
    # Construcción cart — todas las ops de carrito.
    AgenticState.CART_BUILDING: frozenset({
        "list_catalog",
        "add_to_cart",
        "update_cart_item_quantity",
        "remove_cart_item",
        "get_cart",
        "send_product_image",
        _ESCALATE,
    }),
    # Recolección PII — solo tools de contact + consent.
    AgenticState.PII_COLLECTION: frozenset({
        "record_consent",
        "save_contact_field",
        "get_contact_info",
        "get_cart",
        _ESCALATE,
    }),
    # Cotización envío.
    AgenticState.SHIPPING_QUOTE: frozenset({
        "quote_shipping",
        "get_cart",
        "get_contact_info",
        _ESCALATE,
    }),
    # Selección carrier post-cotización.
    AgenticState.CARRIER_SELECTION: frozenset({
        "select_carrier",
        "quote_shipping",
        "get_cart",
        _ESCALATE,
    }),
    # Generación link pago / COD.
    AgenticState.PAYMENT: frozenset({
        "generate_payment_link",
        "get_cart",
        "get_contact_info",
        _ESCALATE,
    }),
    # Post-pago: tracking, status, nuevo pedido.
    AgenticState.POST_PAYMENT: frozenset({
        "get_recent_orders",
        "get_cart",
        "kb_query",
        "list_catalog",
        _ESCALATE,
    }),
    # Humano takeover — sin LLM. Mantenemos escalation por consistencia.
    AgenticState.HUMAN_HANDOFF: frozenset({_ESCALATE}),
}


# Set universal usado por fallback al monolito (todos los tools registrados).
_ALL_TOOLS = frozenset(
    name
    for subset in _TOOLS_BY_STATE.values()
    for name in subset
)


def tools_for_state(state: AgenticState | None) -> frozenset[str]:
    """Retorna tools permitidos para un estado dado.

    state=None → todos los tools (fallback compatibility con monolito).
    """
    if state is None:
        return _ALL_TOOLS
    return _TOOLS_BY_STATE.get(state, _ALL_TOOLS)


def all_known_tool_names() -> frozenset[str]:
    """Union de todos los tools mencionados en la matriz."""
    return _ALL_TOOLS
