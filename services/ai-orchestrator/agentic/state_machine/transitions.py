"""Reglas FSM — qué estados son alcanzables desde cuál.

El resolver determinístico (resolver.py) decide el estado a partir
de evidencia (cart, contact, payments, orders). Este módulo sirve para:

  • Validar transiciones sospechosas (telemetría / observability).
  • Bloquear saltos imposibles (p.ej. GREETING → POST_PAYMENT sin pasar
    por CART_BUILDING + PAYMENT) que indican corrupción de cache.
  • Documentar la jornada para per-state agents (Day 2).

NO se usa para forzar al LLM a un camino — el LLM produce texto dentro
de un estado, no transiciones.
"""
from __future__ import annotations

from agentic.state_machine.states import AgenticState


_TRANSITIONS: dict[AgenticState, frozenset[AgenticState]] = {
    AgenticState.GREETING: frozenset({
        AgenticState.GREETING,
        AgenticState.EXPLORING,
        AgenticState.CART_BUILDING,  # cliente directo "quiero 2 jabones de coco"
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.EXPLORING: frozenset({
        AgenticState.EXPLORING,
        AgenticState.CART_BUILDING,
        AgenticState.GREETING,       # vuelve a saludo si pasó mucho tiempo
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.CART_BUILDING: frozenset({
        AgenticState.CART_BUILDING,
        AgenticState.EXPLORING,      # vacía el cart y vuelve a explorar
        AgenticState.PII_COLLECTION,
        AgenticState.SHIPPING_QUOTE, # si ya tiene contacto, salta a envío
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.PII_COLLECTION: frozenset({
        AgenticState.PII_COLLECTION,
        AgenticState.CART_BUILDING,  # cliente modifica items pre-PII
        AgenticState.SHIPPING_QUOTE,
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.SHIPPING_QUOTE: frozenset({
        AgenticState.SHIPPING_QUOTE,
        AgenticState.CARRIER_SELECTION,
        AgenticState.PII_COLLECTION,    # falta dato adicional
        AgenticState.CART_BUILDING,     # cliente añade item antes de cerrar
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.CARRIER_SELECTION: frozenset({
        AgenticState.CARRIER_SELECTION,
        AgenticState.PAYMENT,
        AgenticState.SHIPPING_QUOTE,    # cliente recalcula (ciudad nueva)
        AgenticState.CART_BUILDING,
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.PAYMENT: frozenset({
        AgenticState.PAYMENT,
        AgenticState.POST_PAYMENT,
        AgenticState.CARRIER_SELECTION, # cliente cambia transportadora
        AgenticState.CART_BUILDING,     # cambio última hora (no debería)
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.POST_PAYMENT: frozenset({
        AgenticState.POST_PAYMENT,
        AgenticState.GREETING,           # nueva conversación post-orden
        AgenticState.HUMAN_HANDOFF,
    }),
    AgenticState.HUMAN_HANDOFF: frozenset({
        AgenticState.HUMAN_HANDOFF,
        AgenticState.GREETING,           # operador devuelve al bot
    }),
}


def is_valid_transition(
    from_state: AgenticState | None,
    to_state: AgenticState,
) -> bool:
    """True si la transición está en la matriz declarada.

    NULL → cualquier estado es válido (rehidratación post-deploy).
    """
    if from_state is None:
        return True
    return to_state in _TRANSITIONS.get(from_state, frozenset())


def allowed_next_states(from_state: AgenticState | None) -> frozenset[AgenticState]:
    if from_state is None:
        return frozenset(AgenticState)
    return _TRANSITIONS.get(from_state, frozenset())


def transition_reason(
    from_state: AgenticState | None,
    to_state: AgenticState,
) -> str:
    """Mensaje legible para logs/observability."""
    if from_state is None:
        return f"rehydrate→{to_state.value}"
    if from_state == to_state:
        return f"stay@{to_state.value}"
    if is_valid_transition(from_state, to_state):
        return f"{from_state.value}→{to_state.value}"
    return f"UNEXPECTED:{from_state.value}→{to_state.value}"
