"""Handler determinístico para display_state=NEEDS_SHIPPING_CITY.

Sem 1 refactor (ADR-0017) — migración desde bypass del orchestrator
introducido en commit 18a3a5d.

Comportamiento:
  • Si cart tiene items con variante resuelta → pregunta ciudad.
  • Si cart vacío + bot listó productos en T-1 → pregunta variante
    (filtrada por mención en inbound si aplica).
  • Si ni A ni B → no aplica (retorna None, dispatcher pasa al LLM).

Origen del fix:
  Bug founder UAT (conv 72e3f77e + bae0f6a2): el LLM, dentro de
  NEEDS_SHIPPING_CITY, redactaba libremente — re-pedía PII a cliente
  conocido, inventaba gramaje. El handler determinístico toma control
  y emite outbound basado en estado del cart, no en libertad del LLM.

Guards (excluyen el handler para no interferir con otros flows):
  • inbound contiene phone update intent → otro path lo maneja.
  • inbound contiene 10 dígitos consecutivos → likely phone, otro path.
  • inbound tiene add_item intent explícito → tier-2 ya disparó arriba.
"""
from __future__ import annotations

import re
from typing import Optional

from fsm import state_renderers
from fsm.handlers.base import HandlerResult, StateHandler, TurnInput
from fsm.handlers.dispatcher import register


class NeedsShippingCityHandler:
    """Handler para NEEDS_SHIPPING_CITY (cart-vacío→variante, cart-armado→ciudad)."""

    applies_to_states = frozenset({"NEEDS_SHIPPING_CITY"})
    priority = 100
    name = "needs_shipping_city.deterministic"

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        # Guard 1: inbound parece phone update (manejado en otro path).
        # Heurística: 10 dígitos consecutivos.
        if turn.inbound_text and re.search(r"\b\+?5?7?\s?\d{10}\b", turn.inbound_text):
            return None

        # Guard 2: add_item intent explícito → tier-2 lo maneja arriba.
        # Detectamos markers de add para cederle el turn.
        if turn.inbound_text and turn.catalog:
            from orchestrator import (  # late import: evita ciclo en init
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

        # Determinar productos presentados en T-1 (para fallback "preguntar variante").
        last_products: list = []
        if turn.history and turn.catalog:
            from orchestrator import _last_outbound_presented_variants_all
            last_products = _last_outbound_presented_variants_all(
                turn.catalog, turn.history,
            )

        cart_items = (turn.cart or {}).get("items") or []
        outbound = state_renderers.render_needs_shipping_city(
            cart_items=cart_items,
            last_outbound_products=last_products,
            inbound_text=turn.inbound_text,
        )
        if not outbound:
            return None

        return HandlerResult(
            outbound_text=outbound,
            handler_name=self.name,
            log_extras={
                "cart_items_count": len(cart_items),
                "last_products_count": len(last_products),
            },
        )


# Auto-registro al importar el módulo.
register(NeedsShippingCityHandler())
