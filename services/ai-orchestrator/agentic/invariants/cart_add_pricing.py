"""Invariant: precio + subtotal al confirmar add_to_cart.

Rev. 108 (founder UAT 2026-05-27): bot dice "Agregué X a tu carrito"
sin mostrar precio unitario ni subtotal. Cliente queda sin saber
cuánto cuesta. UX inadecuado.

Fix arquitectónico: si tool_call_log tiene add_to_cart success Y el
outbound NO incluye un signo de precio ($), reescribimos prepending
los datos de precio + subtotal del cart real (DB-first).

Pattern espejo de `category_completeness`. NO machetazo — detección
determinística + rewrite con datos reales.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


def _add_to_cart_succeeded(tool_call_log: list[dict]) -> Optional[dict]:
    """Retorna el resultado del último add_to_cart success en el log."""
    for call in reversed(tool_call_log or []):
        if call.get("name") == "add_to_cart" and call.get("success"):
            return call.get("result") or {}
    return None


def _outbound_has_price(text: str) -> bool:
    """True si el outbound menciona algún precio ($XX o $XX.XXX)."""
    if not text:
        return False
    return bool(re.search(r"\$\s?\d", text))


def _outbound_has_subtotal(text: str) -> bool:
    """True si el outbound menciona subtotal o total del cart."""
    if not text:
        return False
    return bool(re.search(
        r"\b(?:subtotal|total\s+(?:del\s+)?(?:carrito|cart|pedido))\b",
        text, re.IGNORECASE,
    ))


def _format_cop(cents_or_cop: int, is_cents: bool = False) -> str:
    val = int(cents_or_cop) // 100 if is_cents else int(cents_or_cop)
    return f"${val:,}".replace(",", ".")


def _build_replacement(
    add_result: dict, cart_row: dict, original_text: str,
) -> str:
    """Augmenta outbound: agrega línea Subtotal + reformula línea 'Agregué'
    para incluir precio. PRESERVA el resto del texto LLM (cierre conversacional,
    sugerencias, etc).

    Estrategia:
      1. Detectar línea(s) que afirman add ("Agregué X", "Listo. Agregué X").
      2. Reemplazar SOLO esa línea con versión enriquecida (precio incluido).
      3. Inyectar línea Subtotal después del bloque de adds.
      4. Mantener todo lo demás del LLM (cierres, sugerencias, etc).

    Si no se detecta línea "Agregué" pattern, fallback: prepend datos.
    """
    added = add_result.get("added") or {}
    title = str(added.get("title") or "Producto")
    variant = str(added.get("variant_label") or "").strip()
    qty = int(added.get("quantity") or 1)
    unit_price = int(added.get("unit_price_cop") or 0)
    line_total = unit_price * qty
    subtotal = int(cart_row.get("subtotal_cents") or 0) // 100

    # Línea enriquecida con precio.
    variant_part = f" de {variant}" if variant else ""
    if qty > 1:
        enriched_line = (
            f"Agregué {qty} *{title}*{variant_part} a tu carrito por "
            f"{_format_cop(line_total)} ({_format_cop(unit_price)} c/u)."
        )
    else:
        enriched_line = (
            f"Agregué 1 *{title}*{variant_part} a tu carrito por "
            f"{_format_cop(line_total)}."
        )
    subtotal_line = f"Subtotal: *{_format_cop(subtotal)}*."

    # Detectar bloque "add" — línea con verbo agregar + opcional lista
    # bullets de items que siguen. Captura todo el bloque para reemplazar.
    add_block_pattern = re.compile(
        r"^\s*(?:[¡!]?\s*Listo[\!\.\,]?\s*)?"
        r"(?:Agregu[eé]|He agregado|A[ñn]ad[ií])"
        r"[^\n]*(?:\n\s*[\*\-•][^\n]+)*",
        re.IGNORECASE | re.MULTILINE,
    )

    if not original_text:
        return f"{enriched_line}\n{subtotal_line}"

    match = add_block_pattern.search(original_text)
    if match:
        # Reemplazar el bloque entero "Agregué... + bullets" con versión enriquecida.
        before = original_text[:match.start()].rstrip()
        after = original_text[match.end():].lstrip()
        result = enriched_line + "\n" + subtotal_line
        if before:
            result = before + "\n\n" + result
        if after:
            result = result + "\n\n" + after
        return result

    # Fallback: prepend al texto original.
    return f"{enriched_line}\n{subtotal_line}\n\n{original_text}"


class CartAddPricingInvariant:
    """Asegura que tras add_to_cart success, el outbound muestre
    precio unitario + subtotal del cart.

    Si LLM omite precios (común post múltiples reglas en prompt),
    invariant reescribe con datos reales del cart DB.
    """

    name = "cart_add_pricing"

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
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        # 1. ¿Hubo add_to_cart success?
        add_result = _add_to_cart_succeeded(tool_call_log)
        if not add_result:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="no add_to_cart success en este turno",
            )

        # 2. ¿Outbound ya tiene PRECIO + SUBTOTAL ambos? OK.
        if _outbound_has_price(candidate_text) and _outbound_has_subtotal(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="outbound ya menciona precio y subtotal",
            )

        # 3. Cargar cart actual para subtotal real.
        try:
            cart_q = (
                supabase.table("conversation_carts")
                .select("subtotal_cents, total_cents")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .in_("status", ["open", "checkout"])
                .order("created_at", desc=True).limit(1).execute()
            )
            cart_row = (cart_q.data or [{}])[0]
        except Exception:
            cart_row = {}

        if not cart_row:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="no cart DB encontrado — degradar a LLM",
            )

        # 4. Reescribir.
        replacement = _build_replacement(add_result, cart_row, candidate_text)
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                "add_to_cart success pero outbound no menciona precio. "
                "Rewrite con precio unitario + subtotal real."
            ),
        )
