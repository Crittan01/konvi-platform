"""Mapeo estado → tools permitidos (rev. 109).

Reduce carga cognitiva del LLM: en lugar de 17 tools registradas, cada
estado expone solo las relevantes para su contexto.

Tools globales registradas (17 post rev. 109 founder 2026-05-28):
  list_catalog, get_cart, add_to_cart, update_cart_item_quantity,
  remove_cart_item, get_contact_info, record_consent, save_contact_field,
  quote_shipping, select_carrier, generate_payment_link, escalate_to_human,
  get_recent_orders, kb_query, send_product_image,
  create_claim, get_claim_status  (rev. 109 — agente Reclamos productivo)
"""
from __future__ import annotations

from agentic.state_machine.states import AgenticState


# Tools comunes a múltiples estados (escalation siempre permitido).
_ESCALATE = "escalate_to_human"

# Rev. 109 UAT live BUG 15: cliente con cart activo puede querer modificar
# items en CUALQUIER estado (PII_COLLECTION, SHIPPING_QUOTE, CARRIER_SELECTION,
# PAYMENT). El cart es siempre mutable hasta la orden creada. Extraemos
# CART_MODS para unirlo a todos los estados con cart vivo.
# Rev. 109 UAT live BUG 18: send_product_image + kb_query también deben
# estar disponibles en todos los estados con cart — cliente puede pedir
# foto o info de un producto en cualquier momento del flow.
_CART_MODS = frozenset({
    "add_to_cart",
    "update_cart_item_quantity",
    "remove_cart_item",
    "get_cart",
    "list_catalog",        # cliente puede agregar item adicional
    "send_product_image",  # cliente puede pedir foto en cualquier momento
    "kb_query",            # cliente puede preguntar info de producto/política
    "set_shipping_recipient",  # rev. 109 BUG 37 — receptor alterno
})

# Rev. 109 founder 2026-05-28 — Claims capability. Reclamos pueden surgir
# en CUALQUIER estado donde el cliente esté interactuando (cliente puede
# decir "mi pedido pasado llegó dañado" en medio de una nueva compra).
# Excluye solo HUMAN_HANDOFF (humano ya tomó control).
_CLAIMS_CAPABILITY = frozenset({
    "get_recent_orders",   # para identificar order_id del reclamo
    "create_claim",
    "get_claim_status",
})


def _with_cart_mods(*tools: str) -> frozenset[str]:
    """Helper para construir subset estado-específico + cart mods + escalate +
    claims capability (rev. 109 founder 2026-05-28 — reclamos en cualquier
    estado pre-handoff)."""
    return (
        frozenset(tools)
        | _CART_MODS
        | _CLAIMS_CAPABILITY
        | frozenset({_ESCALATE})
    )


# Mapeo declarativo estado → set de tool names permitidos.
_TOOLS_BY_STATE: dict[AgenticState, frozenset[str]] = {
    # Saludo — cart vacío típicamente; puede saltar a buy directo.
    AgenticState.GREETING: frozenset({
        "list_catalog",
        "add_to_cart",
        "get_contact_info",
        "kb_query",
        "send_product_image",
        _ESCALATE,
    }) | _CLAIMS_CAPABILITY,  # cliente puede iniciar con "tengo un reclamo"
    # Navegación catálogo. Cart vacío típicamente, pero el cliente puede
    # decidir agregar — add_to_cart presente.
    AgenticState.EXPLORING: frozenset({
        "list_catalog",
        "add_to_cart",
        "send_product_image",
        "kb_query",
        "get_contact_info",
        "set_shipping_recipient",  # rev. 109 BUG 37 — receptor alterno
        _ESCALATE,
    }) | _CLAIMS_CAPABILITY,  # rev. 109 — cliente puede reportar reclamo aquí
    # Construcción cart — todas las ops de carrito + foto producto.
    AgenticState.CART_BUILDING: _with_cart_mods(
        "send_product_image",
        "kb_query",
        "get_contact_info",
    ),
    # Recolección PII — tools de contact + consent + cart mods (cliente
    # puede recapacitar items antes de dar datos).
    AgenticState.PII_COLLECTION: _with_cart_mods(
        "record_consent",
        "save_contact_field",
        "get_contact_info",
    ),
    # Cotización envío. Incluye select_carrier para "el más barato"
    # + cart mods por si cliente agrega item olvidado.
    AgenticState.SHIPPING_QUOTE: _with_cart_mods(
        "quote_shipping",
        "select_carrier",
        "get_contact_info",
    ),
    # Selección carrier + opciones de checkout.
    AgenticState.CARRIER_SELECTION: _with_cart_mods(
        "select_carrier",
        "generate_payment_link",
        "quote_shipping",
        "get_contact_info",
    ),
    # Generación link pago / COD. Cliente puede cambiar carrier, agregar
    # last-minute, completar PII, etc.
    AgenticState.PAYMENT: _with_cart_mods(
        "generate_payment_link",
        "select_carrier",
        # A11 2026-06-26 — el cliente puede agregar/quitar productos en PAYMENT
        # (vía _CART_MODS), lo que INVALIDA el envío. Sin quote_shipping aquí el
        # bot no podía recotizar en el mismo turno → presentaba total sin envío.
        "quote_shipping",
        "save_contact_field",
        "record_consent",
        "get_contact_info",
    ),
    # Post-pago: tracking, status, nuevo pedido. Cart de la orden ya está
    # convertido — NO cart mods (la orden es inmutable post-confirm).
    # Rev. 109 founder 2026-05-28 — post-compra es el momento canónico
    # para reclamos (producto llegó dañado, equivocado, etc.). claims
    # capability obligatoria aquí.
    AgenticState.POST_PAYMENT: frozenset({
        "get_recent_orders",
        "get_cart",
        "kb_query",
        "list_catalog",
        _ESCALATE,
    }) | _CLAIMS_CAPABILITY,
    # Humano takeover — sin LLM. Mantenemos escalation por consistencia.
    AgenticState.HUMAN_HANDOFF: frozenset({_ESCALATE}),
}


# Set universal usado por fallback al monolito.
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
