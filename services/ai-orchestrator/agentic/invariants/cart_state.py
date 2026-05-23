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
# Cobertura amplia de conjugaciones (rev. 107 — bug runtime KAIU conv
# bde83d84: bot dijo "ya los agrego a tu pedido" con tool_calls=0 y el
# patrón original `agregu[eé]` solo cubría pretérito, dejaba pasar
# presente/gerundio/futuro). Lista basada en formas conjugadas reales
# observadas en outbounds del LLM, no en raíces ambiguas.
_AFFIRMATIVE_CART_PATTERNS = (
    # agregar: agrego, agregas, agrega, agregamos, agregué, agregó,
    # agregando, agregaré, agregaste — TODAS las conjugaciones útiles.
    re.compile(
        r"\bagreg(?:o|as|a|amos|an|u[eé]|[oó]|ando|ar[eé]|aste)\b",
        re.IGNORECASE,
    ),
    # añadir: añado, añades, añade, añadí, añadió, añadiendo, etc.
    re.compile(
        r"\ba[nñ]ad(?:o|es|e|imos|en|[ií]|i[oó]|iendo|ir[eé])\b",
        re.IGNORECASE,
    ),
    # sumar: sumo, sumas, suma, sumé, sumó, sumamos, sumando.
    re.compile(
        r"\bsum(?:o|as|a|amos|an|[eé]|[oó]|ando|ar[eé])\b",
        re.IGNORECASE,
    ),
    # Frases de cierre clásicas que confirman cart state.
    re.compile(r"\blisto[,.\s]\s*(?:\d+\s*x?\s*)", re.IGNORECASE),
    re.compile(r"\bagregado\s+a\s+tu\s+(?:carrito|pedido|orden)\b", re.IGNORECASE),
    re.compile(r"\bte\s+vend[oa]\b", re.IGNORECASE),
    # "Quedó/Queda/Quedan/Quedaron" agregado/sumado.
    re.compile(
        r"\bqued(?:o|a|an|[oó]|aron)\s+(?:agregad|sumad|a[nñ]adid)[oa]s?\b",
        re.IGNORECASE,
    ),
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


def _count_successful_cart_writes(tool_call_log: list[dict]) -> int:
    """Cuenta cuántos add_to_cart/update/remove ejecutaron con éxito."""
    write_tools = {
        "add_to_cart", "update_cart_item_quantity", "remove_cart_item",
    }
    count = 0
    for call in tool_call_log:
        if call.get("tool") not in write_tools:
            continue
        if "error" not in (call.get("result") or {}):
            count += 1
    return count


def _count_items_affirmed_in_text(text: str) -> int:
    """Estimación de cuántos items distintos el LLM afirma en el outbound.

    Patrón típico WhatsApp del bot:
      * 1x Producto A...
      * 2x Producto B...
      • 1 Jabón de Coco...
      • 1 *Producto C*: $24.000

    Heurística: cuenta bullets que mencionan precio o cantidad+producto.
    NO es 100% precisa — es una señal para el invariant de mismatch.
    """
    if not text:
        return 0
    lines = text.split("\n")
    # Bullet lines con "$" (precio) O con "Nx " al inicio.
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Bullet markers comunes: *, •, -, "•"
        if not (stripped.startswith("*") or stripped.startswith("•")
                or stripped.startswith("-")):
            continue
        # Heurística doble: línea con producto+cantidad o producto+precio.
        if "$" in stripped or re.search(r"\b\d+\s*x?\b", stripped):
            count += 1
    return count


class CartStateInvariant:
    """Doble defensa contra mismatch texto-vs-cart:

    Caso A — LLM afirma cambio pero NO corrió tool de write:
      "Listo, agregué Coco" sin `add_to_cart` exitoso → REWRITE.

    Caso B — LLM lista N items pero solo M < N add_to_cart exitosos:
      "He agregado: Coco 100g + Lavanda 150g" pero solo 1 add_to_cart
      succeeded → la afirmación es PARCIALMENTE falsa. REWRITE para
      que el cliente vea el cart real sin ambigüedad.

    El caso B emerge de bugs runtime donde el LLM compone el mensaje
    final SIN re-verificar resultados de cada tool individual.
    """

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

        # Caso A: afirmación sin ningún tool de write exitoso.
        if not _cart_write_executed(tool_call_log):
            replacement = (
                "Para procesar tu pedido necesito que me confirmes el producto "
                "y la presentación exacta. ¿Cuál te gustaría llevar?"
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    "Caso A: LLM afirmó cambio de cart sin ningún tool "
                    "de write exitoso — rewrite a prompt determinístico."
                ),
            )

        # Caso B: items afirmados > items efectivamente agregados.
        items_affirmed = _count_items_affirmed_in_text(candidate_text)
        items_added = _count_successful_cart_writes(tool_call_log)
        if items_affirmed > items_added and items_affirmed >= 2:
            # El bot listó más items de los que realmente agregó.
            # Reescribir a un prompt honesto que evita ambigüedad.
            replacement = (
                f"Logré agregar {items_added} item(s) al carrito. "
                "Hubo un inconveniente con el otro item. ¿Podrías "
                "repetir cuál te interesa y en qué presentación?"
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    f"Caso B: items_affirmed={items_affirmed} pero "
                    f"items_added={items_added} — mismatch parcial."
                ),
            )

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason="cart write executed coherente con afirmación",
        )
