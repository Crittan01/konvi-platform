"""Handler determinístico para display_state=READY_FOR_SUMMARY.

Sem 1 refactor (ADR-0017) — migración desde bypass del orchestrator
(legacy líneas 9092-9144 antes del refactor).

Comportamiento:
  • Si el último outbound ya fue resumen → no aplica (idempotencia).
  • Si inbound es afirmativo → no aplica (otro path: payment_link).
  • Si inbound es PII update / phone / add_item → no aplica (ceder
    a flujos paralelos que ya corrieron arriba).
  • Si cart tiene items + total > 0 → renderizar resumen determinístico
    con `_build_order_summary_text` (DEPENDENCIA: este builder vive en
    orchestrator.py; Sem 7 lo extraerá a un módulo dedicado).

Guards integrados (eliminan la lógica multiplicativa del monolito):
  • `_last_outbound_was_summary` → idempotencia.
  • `_is_affirmative_confirmation` → cliente confirmó → al payment link.
  • Phone update / 10-digit / add_item / PII update → otros paths.

Origen: bypass `[BYPASS] READY_FOR_SUMMARY → resumen determinístico`.
"""
from __future__ import annotations

import re
from typing import Optional

from fsm.handlers.base import HandlerResult, StateHandler, TurnInput
from fsm.handlers.dispatcher import register


class ReadyForSummaryHandler:
    """Emite resumen determinístico 📋 cuando el cliente llega a
    READY_FOR_SUMMARY con cart completo + datos completos."""

    applies_to_states = frozenset({"READY_FOR_SUMMARY"})
    priority = 100
    name = "ready_for_summary.deterministic_summary"

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        # Late imports: el orchestrator todavía es la fuente de estos
        # helpers; Sem 7 los moveremos a sus propios módulos.
        from orchestrator import (
            _last_outbound_was_summary,
            _is_affirmative_confirmation,
            _detect_shipping_phone_update,
            _detect_data_update_intent,
            _verified_ctx_from_cart,
            _extract_shipping_cost_from_history,
            _extract_shipping_cost_from_db,
            _build_order_summary_text,
            _normalize_text,
            _detect_explicit_products_in_inbound,
        )

        # Guard 1: idempotencia — si el bot ya emitió resumen recientemente,
        # NO re-emitir (cliente lo vio).
        if _last_outbound_was_summary(turn.history or []):
            return None

        # Guard 2: afirmativo → otro path (payment_link) maneja la confirmación.
        if _is_affirmative_confirmation(turn.inbound_text or ""):
            return None

        # Guard 3: PII update intent → otro path (correction / shipping_phone).
        _shipping_phone_intent = _detect_shipping_phone_update(
            turn.inbound_text or "", turn.history or [],
        )
        if _shipping_phone_intent or _detect_data_update_intent(turn.inbound_text or ""):
            return None

        # Guard 4: 10-digit phone (likely respondiendo a pregunta de phone).
        if turn.inbound_text and re.search(r"\b\+?5?7?\s?\d{10}\b", turn.inbound_text):
            return None

        # Guard 5: add_item intent explícito → tier-2 lo maneja arriba.
        if turn.inbound_text and turn.catalog:
            _norm = _normalize_text(turn.inbound_text)
            _add_markers = (
                "agreg", "adicion", "anad", "anadir", "incluy",
                "incorpor", "sumar", "tambien",
            )
            if any(m in _norm for m in _add_markers):
                _matches_pre, _proposals_pre = _detect_explicit_products_in_inbound(
                    turn.inbound_text, turn.catalog,
                )
                if _matches_pre or _proposals_pre:
                    return None

        # Cargar cart fresh — handler no confía en turn.cart porque puede
        # haber cambiado entre stages anteriores.
        cart: Optional[dict] = turn.cart
        if cart is None and turn.supabase is not None:
            try:
                from tools.cart_tool import get_cart_with_items
                cart = get_cart_with_items(
                    turn.supabase,
                    conversation_id=turn.conversation_id,
                    tenant_id=turn.tenant_id,
                )
            except Exception:
                return None

        items = (cart or {}).get("items") or []
        if not items:
            return None

        vctx = _verified_ctx_from_cart(cart)
        if not vctx:
            return None

        # Reconstruir shipping si cart marca requires_requote.
        if not vctx.get("shipping_cost_cents"):
            ship_cents = (
                _extract_shipping_cost_from_history(turn.history or []) or 0
            )
            if not ship_cents and turn.supabase is not None:
                try:
                    ship_cents = _extract_shipping_cost_from_db(
                        turn.supabase, turn.conversation_id,
                    ) or 0
                except Exception:
                    ship_cents = 0
            if ship_cents > 0:
                vctx["shipping_cost_cents"] = ship_cents
                vctx["total_cents"] = (
                    int(vctx.get("subtotal_cents") or 0) + ship_cents
                )

        if int(vctx.get("total_cents") or 0) <= 0:
            return None

        outbound = _build_order_summary_text(
            contact_record=turn.contact_record,
            verified_ctx=vctx,
            catalog=turn.catalog,
            history=turn.history,
            cart_from_db=cart,
        )
        if not outbound:
            return None

        return HandlerResult(
            outbound_text=outbound,
            handler_name=self.name,
            log_extras={
                "cart_items_count": len(items),
                "total_cents": int(vctx.get("total_cents") or 0),
            },
        )


register(ReadyForSummaryHandler())
