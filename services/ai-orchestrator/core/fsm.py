"""FSM canónica del bot conversacional — fuente única de verdad.

Estados nombrados según ``.context/06-contracts.md`` §13. NO renombrar sin
actualizar el contrato.

Diseño:
  - Función pura ``determine_state(facts) -> State`` que computa el estado
    actual a partir de hechos observables (cart, contact, history flags).
  - Tabla ``ALLOWED_TRANSITIONS`` que documenta qué transiciones son válidas;
    los specialists la consultan para validar guard antes de avanzar.
  - El LLM NUNCA decide la transición — solo extrae slots y genera respuesta.

Coherente con Rasa CALM (separación Dialogue Understanding / Business Logic):
  https://rasa.com/docs/rasa-pro/concepts/calm

Coherente con LangGraph supervisor pattern:
  https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class State(str, Enum):
    """Estados canónicos del FSM. Valores estables — usados en logs y tests."""

    CATALOG_MODE = "CATALOG_MODE"
    NEEDS_SHIPPING_CITY = "NEEDS_SHIPPING_CITY"
    AWAITING_CARRIER_SELECTION = "AWAITING_CARRIER_SELECTION"
    NEEDS_CONSENT = "NEEDS_CONSENT"
    NEEDS_EMAIL = "NEEDS_EMAIL"
    NEEDS_NAME = "NEEDS_NAME"
    NEEDS_DOCUMENT = "NEEDS_DOCUMENT"
    NEEDS_DIRECTION = "NEEDS_DIRECTION"
    READY_FOR_SUMMARY = "READY_FOR_SUMMARY"
    AWAITING_ORDER_CONFIRMATION = "AWAITING_ORDER_CONFIRMATION"


@dataclass(frozen=True)
class FsmFacts:
    """Hechos que la FSM consulta. Inmutable — se reconstruye por turno.

    Sin acoplar a Supabase: cada caller arma este dataclass desde sus repos
    y lo pasa a ``determine_state``. Esto permite testear la FSM con cero I/O.
    """

    has_cart_with_items: bool = False
    shipping_quoted: bool = False  # cart.shipping_meta tiene rate_id o equivalent
    carrier_selected: bool = False  # cart.shipping_meta.carrier no nulo
    consent_given: bool = False
    has_email: bool = False
    has_name: bool = False
    has_document: bool = False  # type + number ambos no nulos
    has_complete_address: bool = False
    last_outbound_was_summary_question: bool = False
    last_outbound_was_order_confirm_question: bool = False


# ── Transiciones permitidas ───────────────────────────────────────────────────
#
# Documentadas como mapping de origen → conjunto de destinos válidos. Permite
# auditoría de la máquina sin recorrer código procedural.
#
# Reglas operativas:
#   - CATALOG_MODE es el estado inicial y de fallback.
#   - El usuario puede regresar a CATALOG_MODE desde cualquier estado de
#     recolección si abandona la compra (ej: "déjalo para después"). En la
#     tabla esto se modela explícitamente desde cada NEEDS_* hacia CATALOG_MODE.
#   - READY_FOR_SUMMARY → AWAITING_ORDER_CONFIRMATION es la única transición
#     que dispara creación de orden + payment_link.
#   - AWAITING_ORDER_CONFIRMATION es terminal a nivel FSM (la conversación
#     puede continuar pero el carrito ya pasa a 'checkout' en cart_repo).

_FORWARD: dict[State, set[State]] = {
    State.CATALOG_MODE: {
        State.NEEDS_SHIPPING_CITY,
    },
    State.NEEDS_SHIPPING_CITY: {
        State.AWAITING_CARRIER_SELECTION,
        State.CATALOG_MODE,
    },
    State.AWAITING_CARRIER_SELECTION: {
        State.NEEDS_CONSENT,
        State.NEEDS_SHIPPING_CITY,  # cliente cambia ciudad
        State.CATALOG_MODE,
    },
    State.NEEDS_CONSENT: {
        State.NEEDS_EMAIL,
        State.CATALOG_MODE,  # rechaza consent → vuelve al catálogo
    },
    State.NEEDS_EMAIL: {
        State.NEEDS_NAME,
        State.CATALOG_MODE,
    },
    State.NEEDS_NAME: {
        State.NEEDS_DOCUMENT,
        State.CATALOG_MODE,
    },
    State.NEEDS_DOCUMENT: {
        State.NEEDS_DIRECTION,
        State.CATALOG_MODE,
    },
    State.NEEDS_DIRECTION: {
        State.READY_FOR_SUMMARY,
        State.CATALOG_MODE,
    },
    State.READY_FOR_SUMMARY: {
        State.AWAITING_ORDER_CONFIRMATION,
        # Correcciones: cliente puede pedir corregir un dato, vuelve al estado
        # correspondiente. Estas transiciones de corrección son re-entrantes.
        State.NEEDS_EMAIL,
        State.NEEDS_NAME,
        State.NEEDS_DOCUMENT,
        State.NEEDS_DIRECTION,
    },
    State.AWAITING_ORDER_CONFIRMATION: {
        # Estado terminal a nivel conversacional. El payment_link se genera
        # en la transición; tras el pago Wompi confirma la orden vía webhook
        # (fuera del FSM conversacional).
        State.CATALOG_MODE,  # pago confirmado → cliente queda en modo consulta
    },
}


def is_transition_allowed(*, src: State, dst: State) -> bool:
    """True si ``src → dst`` está permitida según la tabla canónica."""
    return dst in _FORWARD.get(src, set())


def allowed_transitions(src: State) -> frozenset[State]:
    """Conjunto inmutable de destinos permitidos desde ``src``."""
    return frozenset(_FORWARD.get(src, set()))


def determine_state(facts: FsmFacts) -> State:
    """Calcula el estado actual a partir de hechos observables.

    Función pura sin side-effects. Reglas en orden:
      1. Sin items en carrito → CATALOG_MODE (consulta).
      2. Items pero sin cotizar → NEEDS_SHIPPING_CITY.
      3. Cotizado pero sin carrier elegido → AWAITING_CARRIER_SELECTION.
      4. Carrier elegido pero sin consent → NEEDS_CONSENT.
      5. Consent ok pero falta email → NEEDS_EMAIL.
      6. ... y así hasta READY_FOR_SUMMARY.
      7. Si el último outbound fue la pregunta de confirmación de orden,
         estamos esperando que el cliente diga "sí" → AWAITING_ORDER_CONFIRMATION.
    """
    if not facts.has_cart_with_items:
        return State.CATALOG_MODE

    if not facts.shipping_quoted:
        return State.NEEDS_SHIPPING_CITY

    if not facts.carrier_selected:
        return State.AWAITING_CARRIER_SELECTION

    if not facts.consent_given:
        return State.NEEDS_CONSENT

    if not facts.has_email:
        return State.NEEDS_EMAIL

    if not facts.has_name:
        return State.NEEDS_NAME

    if not facts.has_document:
        return State.NEEDS_DOCUMENT

    if not facts.has_complete_address:
        return State.NEEDS_DIRECTION

    if facts.last_outbound_was_order_confirm_question:
        return State.AWAITING_ORDER_CONFIRMATION

    return State.READY_FOR_SUMMARY


# ── Convenience: mapping estado → set de tools permitidos ────────────────────
#
# Usado por ``llm/client.py`` para construir ``ToolConfig.allowed_function_names``
# cuando se llama a Gemini con ``mode="ANY"`` o ``"AUTO"``. Restringe lo que el
# LLM puede invocar según el estado actual.
#
# Ref: https://ai.google.dev/gemini-api/docs/function-calling

ALLOWED_TOOLS_BY_STATE: dict[State, frozenset[str]] = {
    State.CATALOG_MODE: frozenset({
        "search_catalog", "get_product_image", "answer_kb",
        "add_item_to_cart",
    }),
    State.NEEDS_SHIPPING_CITY: frozenset({
        "quote_shipping", "add_item_to_cart", "remove_item_from_cart",
    }),
    State.AWAITING_CARRIER_SELECTION: frozenset({
        "select_carrier", "quote_shipping",
    }),
    State.NEEDS_CONSENT: frozenset({
        "record_consent",
    }),
    State.NEEDS_EMAIL: frozenset({
        "set_customer_email",
    }),
    State.NEEDS_NAME: frozenset({
        "set_customer_name",
    }),
    State.NEEDS_DOCUMENT: frozenset({
        "set_customer_document",
    }),
    State.NEEDS_DIRECTION: frozenset({
        "set_customer_address",
    }),
    State.READY_FOR_SUMMARY: frozenset({
        "render_summary", "set_customer_email", "set_customer_name",
        "set_customer_document", "set_customer_address",
    }),
    State.AWAITING_ORDER_CONFIRMATION: frozenset({
        "confirm_order", "cancel_order",
        # Cliente puede cambiar de opinión y querer agregar/quitar items o
        # corregir un dato antes de confirmar. NO restringir solo a confirm/
        # cancel — eso causa que el LLM con mode=ANY confirme cuando el
        # cliente está pidiendo agregar otra cosa.
        "add_item_to_cart", "remove_item_from_cart",
        "set_customer_email", "set_customer_name",
        "set_customer_document", "set_customer_address",
        "render_summary", "search_catalog", "get_product_image",
    }),
}


def tools_for_state(state: State) -> frozenset[str]:
    """Conjunto de nombres de tools que el LLM puede invocar en ``state``."""
    return ALLOWED_TOOLS_BY_STATE.get(state, frozenset())
