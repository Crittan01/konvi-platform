"""Pre-LLM resolver determinístico: selección de carrier post-quote.

Rev. 108 fix arquitectónico — el LLM agentic Gemini NO siempre llama
`select_carrier` cuando el cliente nombra un carrier después de
`quote_shipping`. Resultado: cart.shipping_cents=0 → resumen sin envío
→ generate_payment_link falla.

Solución determinística: detector pre-LLM que:
  1. Verifica que el bot anterior mostró opciones de envío (cotización).
  2. Detecta nombre de carrier en mensaje cliente (fuzzy match contra
     options del cart.shipping_meta.quoted_options).
  3. Si match → llama `select_carrier_for_cart` directamente.
  4. Marca contexto para que el LLM responda confirmando.

Patrón espejo de `cod_intent_resolver`, `consent_intent_resolver`.
Misma filosofía: determinismo en steps críticos del flow.

NO machetes — esto sí es arquitectura correcta para hybrid LLM + business
rules. El LLM puede ser inestable, pero las TRANSICIONES de state críticas
del cart (carrier_selected, payment_method_chosen, consent_granted) son
determinísticas.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return re.sub(r"[\s_-]+", "", _strip_diacritics(s or "").lower())


# Patrones que indican que el bot anterior cotizó / preguntó carrier.
_BOT_ASKED_CARRIER_PATTERNS = (
    re.compile(r"opciones?\s+de\s+env[ií]o", re.IGNORECASE),
    re.compile(r"cu[áa]l\s+prefieres", re.IGNORECASE),
    re.compile(r"confirmas?\s+el?\s+env[ií]o\s+con", re.IGNORECASE),
    re.compile(
        r"(?:COORDINADORA|SERVIENTREGA|ENVIA|INTERRAPIDISIMO|TCC|"
        r"SAFERBO|DOMINA|99\s?MINUTOS|GO\s?ENVIOS).*\$",
        re.IGNORECASE | re.DOTALL,
    ),
)


def detect_carrier_selection_intent(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    last_bot_outbound: str = "",
) -> Optional[dict]:
    """Detecta si el cliente está seleccionando un carrier ofertado.

    Args:
        supabase: client.
        tenant_id, conversation_id: scope.
        inbound_text: mensaje del cliente.
        last_bot_outbound: último mensaje del bot (debe haber cotizado).

    Returns:
        dict con {carrier_code, rate_id, rate_data} si match, o None.
        El caller debe invocar select_carrier_for_cart con rate_data.
    """
    if not inbound_text or not isinstance(inbound_text, str):
        return None

    # Contexto: bot anterior cotizó / preguntó. Si no, no aplica.
    if last_bot_outbound:
        bot_asked = any(
            p.search(last_bot_outbound) for p in _BOT_ASKED_CARRIER_PATTERNS
        )
        if not bot_asked:
            return None

    # Leer opciones cotizadas del cart (persistidas por quote_shipping).
    try:
        cart_q = (
            supabase.table("conversation_carts")
            .select("id, shipping_meta")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .in_("status", ["open", "checkout"])
            .order("created_at", desc=True).limit(1).execute()
        )
        cart_row = (cart_q.data or [{}])[0]
        shipping_meta = cart_row.get("shipping_meta") or {}
        quoted_options = shipping_meta.get("quoted_options") or []
    except Exception:
        return None

    if not quoted_options:
        return None

    # Buscar nombre de carrier en el inbound.
    inbound_norm = _norm(inbound_text)
    if not inbound_norm:
        return None

    best_match = None
    best_score = 0.0
    for opt in quoted_options:
        carrier_name = opt.get("carrier") or ""
        carrier_norm = _norm(carrier_name)
        if not carrier_norm or len(carrier_norm) < 3:
            continue

        # Direction 1: carrier_norm está EN inbound (cliente nombró el carrier).
        if carrier_norm in inbound_norm:
            score = len(carrier_norm) / max(len(inbound_norm), len(carrier_norm))
            if score > best_score:
                best_score = score
                best_match = opt
            continue

        # Direction 2: inbound está EN carrier_norm (cliente abreviado).
        # Solo si inbound es lo suficientemente específico (≥4 chars).
        if len(inbound_norm) >= 4 and inbound_norm in carrier_norm:
            score = len(inbound_norm) / len(carrier_norm)
            if score > best_score and score >= 0.5:
                best_score = score
                best_match = opt

    if not best_match:
        return None

    return {
        "carrier_code": best_match.get("carrier"),
        "rate_id": best_match.get("rate_id"),
        "rate_data": best_match,
        "confidence": best_score,
        "cart_id": cart_row.get("id"),
    }
