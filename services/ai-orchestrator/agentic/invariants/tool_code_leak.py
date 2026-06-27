"""Invariant: el bot NUNCA filtra una llamada a herramienta como TEXTO al cliente.

Bug runtime KAIU 2026-06-26 (certificación ADR-0026, conv 308c0d0c):
  Cliente: "Perfecto, dame el de 30ml"
  Bot:     "tool_code\nprint(add_to_cart(variation_id='9abc...', quantity=1))"
  Problema: Gemini a veces EMITE la tool-call como texto markdown en vez de
            ejecutarla (falla intermitente del proveedor). El cliente ve código
            crudo Y la acción (agregar) NO ocurre. Pésima coherencia.

Defensa en profundidad post-LLM, determinística (ADR-0024: detección binaria por
regex de firmas de tool-call, NO parser NLP). Si aparece, REESCRIBE a un mensaje
seguro que re-engancha sin exponer internals ni dejar al cliente colgado.

NO bloquea — REWRITE.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)

logger = logging.getLogger(__name__)

# Nombres de tools reales del orquestador (para detectar la llamada como texto).
_TOOL_NAMES = (
    "add_to_cart", "remove_cart_item", "update_cart_item_quantity",
    "quote_shipping", "select_carrier", "generate_payment_link",
    "save_contact_field", "save_address", "record_consent", "list_catalog",
    "send_product_image", "get_order_status", "apply_coupon",
)

# Firmas binarias de fuga de tool-call (cualquiera = leak):
_LEAK_PATTERNS = (
    # Marcador/fence de Gemini "tool_code".
    re.compile(r"(?:^|\n)\s*`{0,3}\s*tool_code\b", re.IGNORECASE),
    # print(tool(...)) — patrón típico de la fuga.
    re.compile(r"\bprint\s*\(\s*\w+\s*\("),
    # Un tool real invocado como texto: add_to_cart( / quote_shipping( ...
    re.compile(r"\b(?:" + "|".join(_TOOL_NAMES) + r")\s*\("),
    # Fence de código con kwargs típicos de tool-call.
    re.compile(r"```[a-z_]*\s*\n[^`]*\b(?:variation_id|product_id|rate_id)\s*="),
)

_SAFE_RECOVERY = (
    "Perdón, se me cruzó un detalle técnico por un segundo. "
    "¿Me repites qué necesitas y seguimos sin problema?"
)


def _has_leak(text: str) -> bool:
    return bool(text) and any(p.search(text) for p in _LEAK_PATTERNS)


class ToolCodeLeakInvariant:
    """REWRITE si el outbound filtra una tool-call como texto (Gemini emitió la
    llamada en vez de ejecutarla). Garantiza que el cliente NUNCA vea código."""

    name = "tool_code_leak"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
        inbound_text: str = "",
    ) -> InvariantResult:
        if not _has_leak(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        logger.warning(
            "[INVARIANT] tool_code_leak REWRITE conv=%s — Gemini filtró una "
            "tool-call como texto; reemplazado por recovery seguro.",
            conversation_id[:8] if conversation_id else "?",
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=_SAFE_RECOVERY,
            reason="outbound filtraba una tool-call como texto (leak de Gemini)",
        )
