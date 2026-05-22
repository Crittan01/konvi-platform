"""Invariant: cart-state coherente con outbound LLM.

ADR-0018. Si el LLM afirma "agregué X" en el outbound pero `get_cart()`
muestra que X NO está, BLOCK + emit prompt determinístico pidiendo
variante (caso runtime conv 4cb7477d).

Esto cierra el gap que hizo posible el bug "bot dice Listo, cart vacío".
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    Invariant,
    InvariantOutcome,
    InvariantResult,
)


# Patrones que el LLM puede usar para afirmar cart-state.
_AFFIRMATIVE_CART_PATTERNS = (
    re.compile(r"\b(agregu[eé]|a[nñ]ad[ií]|sumar|sum[eé])\b", re.IGNORECASE),
    re.compile(r"\blisto[,.\s]\s*(?:\d+\s*x?\s*)", re.IGNORECASE),
    re.compile(r"\bagregado\s+a\s+tu\s+carrito\b", re.IGNORECASE),
    re.compile(r"\bte\s+vend[oa]\b", re.IGNORECASE),
)


def _llm_affirms_cart_change(text: str) -> bool:
    """True si el outbound del LLM afirma haber modificado el cart."""
    if not text:
        return False
    return any(p.search(text) for p in _AFFIRMATIVE_CART_PATTERNS)


def _cart_write_executed(tool_call_log: list[dict]) -> bool:
    """True si en este turn corrió un tool de write al cart (con éxito)."""
    write_tools = {
        "add_to_cart", "update_cart_item_quantity", "remove_cart_item",
    }
    for call in tool_call_log:
        if call.get("tool") not in write_tools:
            continue
        result = call.get("result") or {}
        # Tool failure tiene "error" key — éxito NO.
        if "error" not in result:
            return True
    return False


class CartStateInvariant:
    """Si LLM afirma cambio de cart, ese cambio debe haber pasado por
    un tool de write del cart en este turn."""

    name = "cart_state_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
    ) -> InvariantResult:
        if not _llm_affirms_cart_change(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        if _cart_write_executed(tool_call_log):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="cart write executed, LLM afirmación es válida",
            )
        # LLM afirma cambio pero NO corrió tool de write.
        replacement = (
            "Para procesar tu pedido necesito que me confirmes el producto "
            "y la presentación exacta. ¿Cuál te gustaría llevar?"
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                "LLM afirmó cambio de cart sin tool de write — rewrite "
                "a prompt determinístico (anti-hallu)"
            ),
        )
