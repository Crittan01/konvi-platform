"""Handler determinístico para display_state=NEEDS_CONSENT.

Sem 1.3 refactor (ADR-0017) — migración desde bypass del orchestrator
(legacy líneas 8720-8767 antes del refactor).

Comportamiento:
  Cliente recién pasó el carrier-selection; bot debe pedir consent
  Habeas Data. Si el cliente dijo "sigamos"/"continuemos" SIN elegir
  carrier explícitamente, prepend ack del carrier auto-defaulteado
  (Económica) para que el cliente vea qué se eligió antes del consent
  question.

Origen UAT (s9 feedback): "el chat no confirmó cuál tipo de envío y
supuso económico".

Sin guards complejos — el state NEEDS_CONSENT es resuelto por FSM solo
cuando consent_given=False Y todo lo anterior está OK.
"""
from __future__ import annotations

from typing import Optional

from fsm.handlers.base import HandlerResult, StateHandler, TurnInput
from fsm.handlers.dispatcher import register


class NeedsConsentHandler:
    """Handler para NEEDS_CONSENT: pide consent Habeas Data con ack opcional
    del carrier auto-defaulteado."""

    applies_to_states = frozenset({"NEEDS_CONSENT"})
    priority = 100
    name = "needs_consent.deterministic"

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        # Late imports — Sem 7 los moveremos a sus módulos.
        from orchestrator import (
            CONSENT_QUESTION_TEMPLATE,
            _normalize_text,
            _extract_shipping_carrier_from_history,
            _extract_shipping_cost_from_history,
            _format_cop,
        )

        consent_text = CONSENT_QUESTION_TEMPLATE
        norm_content = _normalize_text(turn.inbound_text or "")

        # Continue-intent tokens — cliente dice "sigamos"/"continuemos"
        # sin elegir carrier explícitamente.
        _continue_intent = {
            "sigamos", "continuemos", "continuar", "continua", "continúa",
            "procedamos", "compra", "comprar", "avancemos", "sigue",
        }
        _explicit_carrier_tokens = (
            "economica", "rapida", "deprisa", "servientrega",
            "coordinadora", "tcc", "dhl", "fedex", "interrapidisimo",
            "mensajeros", "urbanos",
        )
        user_picked_explicitly = any(t in norm_content for t in _explicit_carrier_tokens)

        if (
            not user_picked_explicitly
            and any(t in norm_content.split() for t in _continue_intent)
        ):
            carrier_name = _extract_shipping_carrier_from_history(turn.history or [])
            shipping_cents = (
                _extract_shipping_cost_from_history(turn.history or []) or 0
            )
            if carrier_name and shipping_cents > 0:
                carrier_ack = (
                    f"Listo, voy con la opción *Económica* "
                    f"({carrier_name}) por *{_format_cop(shipping_cents)}*.\n\n"
                )
                consent_text = carrier_ack + consent_text

        return HandlerResult(
            outbound_text=consent_text,
            handler_name=self.name,
            log_extras={
                "user_picked_explicitly": user_picked_explicitly,
            },
        )


register(NeedsConsentHandler())
