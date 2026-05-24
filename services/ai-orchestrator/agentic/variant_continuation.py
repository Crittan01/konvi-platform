"""Pre-LLM resolver determinístico: continuación de selección de variante.

Caso founder runtime KAIU 2026-05-24 conv 8c845cc0 turn 3:
  Bot:     "Para el Sérum de Vitamina C, tenemos dos presentaciones:
            * 30ml por $85.000 COP
            * 15ml por $52.000 COP
            Cuál te gustaría llevar?"
  Cliente: "15ml"
  → Gemini emite STOP+empty con tools (saturación SDK).
  → text-only retry recupera texto "agregué Sérum 15ml" pero sin tools.
  → CartStateInvariant atrapa la mentira → rewrite "Cuéntame de nuevo".
  → UX rota: cliente NO debe sufrir Gemini SDK quirks.

Solución arquitectónica: cuando el contexto es DETERMINÍSTICO (bot
preguntó variantes X/Y, cliente respondió X), bypaseamos Gemini y
resolvemos directamente. Sin parches retry, sin dudas. El bot ejecuta
add_to_cart + emite texto natural.

NO usa LLM — pura lógica determinística (regex + catalog lookup). Esto
es exactamente el patrón ya existente para `image_send_tool`,
`shipping_quote_tool`, `order_status_tool` en `tools/inbound_dispatcher`
(legacy V1) — extender la cobertura a "variant selection continuation"
para el flow agentic.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional


# Regex para detectar respuesta corta de variante del cliente:
#   "15ml" / "30 ml" / "100g" / "150 gramos" / "el de 30" / "30ml por favor"
_INBOUND_VARIANT_PATTERNS = (
    re.compile(
        r"^\s*(?:el\s+de\s+|los?\s+de\s+|la\s+de\s+)?"
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(ml|gr?|g|gramos?|kg|kilogramos?|oz|onzas?|l|lts?|litros?)"
        r"\s*(?:por\s+favor|porfa|por\s+favorcito)?\s*[.!?]*\s*$",
        re.IGNORECASE,
    ),
    # Variante de "Solo número" en contextos donde es obvio (e.g. "30").
    # NO lo cubrimos por ahora — demasiado ambiguo sin lookup.
)


def _strip_diacritics(s: str) -> str:
    """Bogotá → Bogota; útil para matching insensible a tildes."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_variant(value: str, unit: str) -> str:
    """Normaliza '30 ml' → '30ml', '100 gramos' → '100g', etc."""
    unit_lower = unit.lower().strip()
    # Sinónimos comunes.
    if unit_lower in ("gramos", "gramo", "gr"):
        unit_lower = "g"
    if unit_lower in ("kilogramos", "kilogramo", "kg"):
        unit_lower = "kg"
    if unit_lower in ("onzas", "onza"):
        unit_lower = "oz"
    if unit_lower in ("litros", "litro", "lts", "lt"):
        unit_lower = "l"
    # Quita decimales triviales (15.0 → 15).
    try:
        n = float(value.replace(",", "."))
        if n.is_integer():
            value = str(int(n))
    except ValueError:
        pass
    return f"{value}{unit_lower}"


def _extract_client_variant(inbound_text: str) -> Optional[str]:
    """Si el inbound es respuesta-de-variante única, retorna 'Xml'/'Xg' normalizado.
    Sino retorna None.
    """
    text = (inbound_text or "").strip()
    if not text or len(text) > 50:
        return None
    for pat in _INBOUND_VARIANT_PATTERNS:
        m = pat.match(text)
        if m:
            return _normalize_variant(m.group(1), m.group(2))
    return None


# Detectar producto + variantes ofrecidas en el ÚLTIMO outbound del bot:
#   "Para el *Sérum de Vitamina C*, tenemos dos presentaciones:
#    * 30ml por $85.000 COP
#    * 15ml por $52.000 COP"
_BOT_OFFERED_VARIANTS_PATTERN = re.compile(
    r"\b(?:para\s+(?:el|la|los|las|tu)|del?)\s+\*?([A-ZÁÉÍÓÚÑa-záéíóúñ][^*\n.]{2,60}?)\*?[,.:]?\s+"
    r"(?:tenemos|prefieres|cuál|qu[eé]\s+presentaci[oó]n)",
    re.IGNORECASE,
)


def _extract_product_from_bot_question(outbound_text: str) -> Optional[str]:
    """Extrae el nombre del producto del que el bot preguntó variante."""
    if not outbound_text:
        return None
    # Busca primero patrón "Para el *Producto X*, tenemos..."
    m = _BOT_OFFERED_VARIANTS_PATTERN.search(outbound_text)
    if m:
        candidate = m.group(1).strip()
        # Limpia markdown bold residual + puntuación.
        candidate = re.sub(r"[*_~`]", "", candidate).strip(" .,:")
        return candidate or None
    return None


def _bot_outbound_contains_variant_options(outbound_text: str) -> bool:
    """True si el outbound del bot presenta múltiples variantes con precio.

    Cubre varios formatos comunes del bot:
      * Bulleted:  "* 30ml por $85.000" o "* 30ml: $85.000"
      * Inline:    "*30ml* ($85.000) o *15ml* ($52.000)?"
      * Lista:     "• 30ml — $85.000"
    Heurística robusta: cuenta ocurrencias de "Xml/Xg" + un símbolo $ a
    distancia ≤ 30 caracteres después.
    """
    if not outbound_text:
        return False
    # Cuenta tokens variant (Xml/Xg/etc.) seguidos en ≤30 chars por $.
    matches = re.findall(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|gr?|g|gramos?|kg|oz|l)\b[^\n]{0,30}?\$",
        outbound_text,
        re.IGNORECASE,
    )
    return len(matches) >= 2


def _normalize_for_matching(s: str) -> str:
    """Lowercase + strip diacritics + collapse spaces, para matching robusto."""
    s2 = _strip_diacritics((s or "").lower())
    return re.sub(r"\s+", " ", s2).strip()


def _find_product_in_catalog(
    product_hint: str, catalog: list[dict],
) -> Optional[dict]:
    """Busca un producto del catalog cuyo título matchee `product_hint`.

    Match: lowercased + sin tildes + substring contains. Si hay múltiples
    matches → None (ambiguo, mejor no resolver).
    """
    if not product_hint or not catalog:
        return None
    hint_norm = _normalize_for_matching(product_hint)
    # Quitar artículos comunes.
    hint_norm = re.sub(
        r"^(?:el|la|los|las|un|una|unos|unas)\s+", "", hint_norm,
    ).strip()
    if not hint_norm:
        return None

    matches = []
    for prod in catalog:
        title = _normalize_for_matching(str(prod.get("title") or ""))
        if not title:
            continue
        # Hint en title O title en hint (parcial).
        if hint_norm in title or title in hint_norm:
            matches.append(prod)
    if len(matches) == 1:
        return matches[0]
    return None


def _find_variation_by_label(
    product: dict, variant_str: str,
) -> Optional[dict]:
    """Busca variation con label que matchea `variant_str` (normalizado)."""
    variants = product.get("variants") or []
    target = _normalize_for_matching(variant_str)
    for v in variants:
        label_norm = _normalize_for_matching(str(v.get("label") or ""))
        # Match flexible: "30ml" matches "30 ml" o "30ml" o "30 mililitros".
        # Normalizamos ambos para reducir a "30ml".
        label_clean = re.sub(r"\s+", "", label_norm)
        target_clean = re.sub(r"\s+", "", target)
        if label_clean == target_clean:
            return v
    return None


def try_resolve_variant_continuation(
    *,
    inbound_text: str,
    history: list,
    catalog: list[dict],
) -> Optional[dict]:
    """Detecta el patrón "bot preguntó variantes + cliente respondió" y
    resuelve product_id + variation_id determinísticamente.

    Returns:
      dict {
        "product_id": str,
        "variation_id": str,
        "product_title": str,
        "variant_label": str,
        "unit_price_cop": float,
      } si match único, None si no aplica.
    """
    # 1. ¿Inbound del cliente es respuesta corta de variante?
    client_variant = _extract_client_variant(inbound_text)
    if not client_variant:
        return None

    # 2. ¿El último outbound del bot presentó variantes?
    last_bot_outbound = None
    for msg in reversed(history or []):
        if (msg.get("direction") or "").lower() == "outbound":
            last_bot_outbound = str(msg.get("content") or "")
            break
    if not last_bot_outbound:
        return None
    if not _bot_outbound_contains_variant_options(last_bot_outbound):
        return None

    # 3. ¿Qué producto se discute?
    product_hint = _extract_product_from_bot_question(last_bot_outbound)
    if not product_hint:
        return None

    # 4. Resolver en catalog.
    product = _find_product_in_catalog(product_hint, catalog)
    if not product:
        return None
    variation = _find_variation_by_label(product, client_variant)
    if not variation:
        return None

    return {
        "product_id": str(product.get("id") or ""),
        "variation_id": str(variation.get("id") or ""),
        "product_title": str(product.get("title") or ""),
        "variant_label": str(variation.get("label") or ""),
        "unit_price_cop": float(variation.get("price") or 0),
    }
