"""Handler determinístico para display_state=AWAITING_CARRIER_SELECTION.

Sem 1 refactor (ADR-0017) — migración desde bypass del orchestrator
(commit 18a3a5d).

Comportamiento:
  • Si el último outbound fue una cotización con opciones Económica/Rápida
    → recordar al cliente las opciones.
  • Si no hubo cotización reciente (LLM se desvió de tema) → no aplica.

Guards: idénticos a NeedsShippingCityHandler (phone update / add_item
intent ceden el turn).
"""
from __future__ import annotations

from typing import Optional

from fsm import state_renderers
from fsm.handlers.base import HandlerResult, StateHandler, TurnInput
from fsm.handlers.dispatcher import register


class AwaitingCarrierSelectionHandler:
    """Handler para AWAITING_CARRIER_SELECTION (recuerda Económica/Rápida)."""

    applies_to_states = frozenset({"AWAITING_CARRIER_SELECTION"})
    priority = 100
    name = "awaiting_carrier_selection.deterministic"

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        import re

        # Guard 1: 10-digit phone update — let other path handle it.
        if turn.inbound_text and re.search(r"\b\+?5?7?\s?\d{10}\b", turn.inbound_text):
            return None

        # Guard 2: add_item intent → tier-2 handles arriba.
        if turn.inbound_text and turn.catalog:
            from orchestrator import (
                _normalize_text,
                _detect_explicit_products_in_inbound,
            )
            _norm = _normalize_text(turn.inbound_text)
            _add_markers = (
                "agreg", "adicion", "anad", "anadir", "incluy",
                "incorpor", "sumar",
            )
            if any(m in _norm for m in _add_markers):
                _m, _p = _detect_explicit_products_in_inbound(
                    turn.inbound_text, turn.catalog,
                )
                if _m or _p:
                    return None

        last_was_quote = state_renderers.last_outbound_was_shipping_quote(
            turn.history or [],
        )
        outbound = state_renderers.render_awaiting_carrier_selection(
            last_outbound_was_quote=last_was_quote,
        )
        if not outbound:
            return None

        return HandlerResult(
            outbound_text=outbound,
            handler_name=self.name,
            log_extras={"last_was_quote": last_was_quote},
        )


register(AwaitingCarrierSelectionHandler())
