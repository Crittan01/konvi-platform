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


_CART_AFFIRMATION_ANCHORS = (
    re.compile(r"\b(?:ya\s+)?(?:agregu[eé]|sum[eé]|a[nñ]ad[ií])\b", re.IGNORECASE),
    re.compile(r"\bhe\s+agregado\b", re.IGNORECASE),
    re.compile(r"\btu\s+(?:carrito|pedido|orden)\s+(?:incluye|contiene|tiene|actual)\b", re.IGNORECASE),
    re.compile(r"\b(?:pedido|carrito)\s+actual[:\s]", re.IGNORECASE),
    re.compile(r"\blisto[,.]?\s*\d", re.IGNORECASE),
    re.compile(r"\bqued(?:ó|aron)\s+(?:agregad|sumad)", re.IGNORECASE),
)

_VARIANT_PRESENTATION_ANCHORS = (
    re.compile(r"\bpresentacion(?:es)?\b", re.IGNORECASE),
    re.compile(r"\bcu[aá]l\s+(?:te|presentaci[oó]n|prefieres|escoges|eliges)", re.IGNORECASE),
    re.compile(r"\btenemos\s+est[ao]s?\b", re.IGNORECASE),
    re.compile(r"\bopciones?\s+disponibles?", re.IGNORECASE),
    # Rev. 108 holístico — carrier presentation patterns. Cuando bot
    # presenta opciones de envío post-quote_shipping, los bullets son
    # carriers no items. Sin estos anchors, _count_items_affirmed_in_text
    # cuenta los bullets de carriers ($price) como items → falso positivo
    # Case B → REWRITE incorrecto "Hubo un inconveniente con el otro item".
    re.compile(r"\bopciones?\s+de\s+env[ií]o", re.IGNORECASE),
    re.compile(r"\bpara\s+(?:el\s+)?env[ií]o\s+a\b", re.IGNORECASE),
    re.compile(r"\btransportador(?:a|as)\s+disponibles?", re.IGNORECASE),
    re.compile(r"\bcarriers?\s+disponibles?", re.IGNORECASE),
    re.compile(
        r"\b(?:COORDINADORA|SERVIENTREGA|ENVIA|INTERRAPIDISIMO|TCC|"
        r"DOMINA|SAFERBO|99\s?MINUTOS|GO\s?ENVIOS)\b.*\$",
        re.IGNORECASE | re.DOTALL,
    ),
)


def _count_items_affirmed_in_text(text: str) -> int:
    """Cuenta bullets que el LLM AFIRMA como items en cart real.

    Rev. 107 fix runtime KAIU 2026-05-24: el conteo previo era una
    heurística simple ("bullet con $ o cantidad = item"), pero generaba
    falso positivo cuando el bot lista VARIANTES disponibles de un
    producto que el cliente aún no eligió. Ej:

        "Perfecto, agregué 2 *Jabones Coco* 100g a tu carrito.
         Para el *Sérum de Vitamina C* tenemos estas presentaciones:
         * 15ml: $52.000
         * 30ml: $85.000
         Cuál te gustaría?"

    El bot YA agregó solo 1 item (jabón); los 2 bullets siguientes son
    OPCIONES presentadas, no items afirmados. La heurística vieja contaba
    2 → Case B disparaba REWRITE incorrecto.

    Algoritmo nuevo:
      1. Localizar líneas-ancla que afirman cart-write ("ya agregué",
         "tu pedido incluye", etc.). Si NO hay ancla → return 0 (no es
         un mensaje afirmativo de cart).
      2. Localizar líneas-ancla de presentación de variantes
         ("presentaciones", "cuál te gustaría", "opciones disponibles").
      3. Solo contar bullets que aparezcan ENTRE una ancla cart-write y
         (la siguiente ancla de presentación de variantes O el final
         del texto, lo que ocurra primero).
    """
    if not text:
        return 0
    lines = text.split("\n")

    cart_anchor_idx = None
    variant_anchor_idx = None
    for i, line in enumerate(lines):
        if cart_anchor_idx is None and any(p.search(line) for p in _CART_AFFIRMATION_ANCHORS):
            cart_anchor_idx = i
        elif cart_anchor_idx is not None and variant_anchor_idx is None \
                and any(p.search(line) for p in _VARIANT_PRESENTATION_ANCHORS):
            variant_anchor_idx = i

    if cart_anchor_idx is None:
        return 0  # Ninguna afirmación de cart-write → bullets son opciones.

    end_idx = variant_anchor_idx if variant_anchor_idx is not None else len(lines)
    count = 0
    for line in lines[cart_anchor_idx:end_idx]:
        stripped = line.strip()
        if not stripped:
            continue
        if not (stripped.startswith("*") or stripped.startswith("•")
                or stripped.startswith("-")):
            continue
        if "$" in stripped or re.search(r"\b\d+\s*x?\b", stripped):
            count += 1
    return count


def _case_a_replacement(inbound_text: str, candidate_text: str) -> str:
    """Construye el rewrite para Case A — NUNCA delatar sistema.

    Rev. 107 founder feedback 2026-05-24: NUNCA usar "problema técnico"
    ni jerga que delate el bot. El cliente solo debe ver una pregunta
    natural que mantenga el momentum comercial.

    El parámetro `inbound_text` se mantiene en signature por compat
    futura — variantes específicas del replacement se podrían usar
    si hay heurística clara, pero por ahora SIEMPRE el mismo mensaje
    natural y honesto (no inventa una "razón técnica").
    """
    # Replacement único, natural, sin jerga, sin delatar bot.
    return (
        "Cuéntame de nuevo qué producto y presentación quieres y te "
        "lo agrego al carrito enseguida."
    )


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
        inbound_text: str = "",
    ) -> InvariantResult:
        if not _llm_affirms_cart_change(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Caso A: afirmación sin ningún tool de write exitoso.
        if not _cart_write_executed(tool_call_log):
            replacement = _case_a_replacement(inbound_text, candidate_text)
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    "Caso A: LLM afirmó cambio de cart sin ningún tool "
                    "de write exitoso — rewrite a prompt determinístico."
                ),
            )

        # Caso B (rev. 107 refactor): items afirmados > items en CART REAL.
        # Antes comparábamos contra add_to_cart EXITOSOS THIS TURN, lo
        # cual generaba falso positivo cuando el bot lista cart total
        # (acumulado) tras agregar 1 item nuevo: outbound mostraba 3 items
        # pero solo 1 add_to_cart corrió este turn → REWRITE incorrecto.
        # Fix: cargar cart REAL desde DB y comparar contra items_in_cart_total.
        # Sólo si bot lista MÁS items de los que cart real tiene → REWRITE.
        items_affirmed = _count_items_affirmed_in_text(candidate_text)
        if items_affirmed >= 2:
            cart_items_count = await _get_cart_items_count(
                supabase, conversation_id, tenant_id,
            )
            if cart_items_count is not None and items_affirmed > cart_items_count:
                items_added_this_turn = _count_successful_cart_writes(tool_call_log)
                replacement = (
                    f"Logré agregar {items_added_this_turn} item(s) al "
                    "carrito. Hubo un inconveniente con el otro item. "
                    "¿Podrías repetir cuál te interesa y en qué presentación?"
                )
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text=replacement,
                    reason=(
                        f"Caso B: items_affirmed={items_affirmed} pero "
                        f"cart real tiene {cart_items_count} — mismatch real."
                    ),
                )

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason="cart write executed coherente con afirmación",
        )


async def _get_cart_items_count(
    supabase: Any, conversation_id: str, tenant_id: str,
) -> Optional[int]:
    """Cuenta items distintos en el cart real (DB). Returns None si falla
    (best-effort — el invariant degrada a OK para no bloquear cliente)."""
    try:
        cart_row = (
            supabase.table("conversation_carts")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("status", "open")
            .limit(1)
            .execute()
        )
        if not cart_row.data:
            return 0  # No hay cart abierto → 0 items.
        cart_id = cart_row.data[0]["id"]
        items_res = (
            supabase.table("conversation_cart_items")
            .select("id")
            .eq("cart_id", cart_id)
            .execute()
        )
        return len(items_res.data or [])
    except Exception:
        return None
