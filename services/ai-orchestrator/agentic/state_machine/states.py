"""Enum canónico de estados del Inbox agentic.

Los valores string DEBEN coincidir con el CHECK constraint de
`conversations.agentic_state` (migración 20260604000000).
"""
from __future__ import annotations

from enum import Enum


class AgenticState(str, Enum):
    """Estados del state machine.

    Orden lógico de la jornada (no es una rígida secuencia — el resolver
    puede saltar hacia atrás si el cart se vacía, por ejemplo):

      GREETING           — saludo inicial / re-engage tras inactividad
      EXPLORING          — cliente navega categorías, aún 0 items
      CART_BUILDING      — cart con ≥1 item, sin checkout iniciado
      PII_COLLECTION     — capturando contacto (consent Habeas Data activo)
      SHIPPING_QUOTE     — cotización envío en curso (Aveonline)
      CARRIER_SELECTION  — cliente eligiendo entre opciones de envío
      PAYMENT            — método pago / link Wompi / COD pendiente
      POST_PAYMENT       — orden creada, esperando confirmación final / tracking
      HUMAN_HANDOFF      — bot fuera, asesor humano (conversations.status=human_takeover)
    """

    GREETING = "GREETING"
    EXPLORING = "EXPLORING"
    CART_BUILDING = "CART_BUILDING"
    PII_COLLECTION = "PII_COLLECTION"
    SHIPPING_QUOTE = "SHIPPING_QUOTE"
    CARRIER_SELECTION = "CARRIER_SELECTION"
    PAYMENT = "PAYMENT"
    POST_PAYMENT = "POST_PAYMENT"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"

    @classmethod
    def from_db(cls, value: str | None) -> "AgenticState | None":
        """Lee el valor de conversations.agentic_state, NULL-safe."""
        if not value:
            return None
        try:
            return cls(value)
        except ValueError:
            return None

    @property
    def is_pre_cart(self) -> bool:
        return self in {AgenticState.GREETING, AgenticState.EXPLORING}

    @property
    def is_checkout(self) -> bool:
        return self in {
            AgenticState.PII_COLLECTION,
            AgenticState.SHIPPING_QUOTE,
            AgenticState.CARRIER_SELECTION,
            AgenticState.PAYMENT,
        }

    @property
    def is_terminal(self) -> bool:
        return self in {AgenticState.POST_PAYMENT, AgenticState.HUMAN_HANDOFF}
