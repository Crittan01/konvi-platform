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
    # "15ml" / "el de 30ml" / "30 ml por favor"
    re.compile(
        r"^\s*(?:el\s+de\s+|los?\s+de\s+|la\s+de\s+|"
        r"dame\s+(?:el\s+de\s+)?|quiero\s+(?:el\s+de\s+)?|"
        r"prefiero\s+(?:el\s+de\s+)?)?"
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(ml|gr?|g|gramos?|kg|kilogramos?|oz|onzas?|l|lts?|litros?)"
        r"\s*(?:por\s+favor|porfa|por\s+favorcito|entonces)?\s*[.!?]*\s*$",
        re.IGNORECASE,
    ),
)

# Pattern para "solo número" — válido SOLO cuando el bot acaba de
# presentar variantes con UN tipo único de unidad (e.g., todas en ml).
# Rev. 107 fix runtime KAIU 2026-05-24: cliente dijo "Dame el de 30
# entonces" tras bot presentar 15ml/30ml. Resolver no detectaba porque
# regex requería unidad explícita.
_INBOUND_NUMBER_ONLY_PATTERN = re.compile(
    r"^\s*(?:el\s+de\s+|los?\s+de\s+|la\s+de\s+|"
    r"dame\s+(?:el\s+de\s+)?|quiero\s+(?:el\s+de\s+)?|"
    r"prefiero\s+(?:el\s+de\s+)?|me\s+gusta\s+(?:el\s+de\s+)?)?"
    r"(\d+(?:[.,]\d+)?)"
    r"\s*(?:por\s+favor|porfa|entonces|gracias)?\s*[.!?]*\s*$",
    re.IGNORECASE,
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


def _extract_client_variant(
    inbound_text: str,
    *,
    fallback_unit: Optional[str] = None,
) -> Optional[str]:
    """Si el inbound es respuesta-de-variante única, retorna 'Xml'/'Xg' normalizado.
    Sino retorna None.

    `fallback_unit` (opcional, rev. 107 fix runtime 2026-05-24): si el
    cliente responde solo con número ("Dame el de 30") sin unidad,
    intentamos completar con la unidad común del último outbound del
    bot (e.g., bot presentó "15ml/30ml" → fallback_unit="ml"). Sin esto
    el resolver fallaba para respuestas naturales como "30" o "el de 30".
    """
    text = (inbound_text or "").strip()
    if not text or len(text) > 50:
        return None
    # Primero intentar con unidad explícita.
    for pat in _INBOUND_VARIANT_PATTERNS:
        m = pat.match(text)
        if m:
            return _normalize_variant(m.group(1), m.group(2))
    # Fallback: número-only matchea Y bot presentó variantes con misma unidad.
    if fallback_unit:
        m = _INBOUND_NUMBER_ONLY_PATTERN.match(text)
        if m:
            return _normalize_variant(m.group(1), fallback_unit)
    return None


# Detecta la unidad COMÚN entre las variantes ofrecidas por el bot
# (e.g. "15ml por $X o 30ml por $Y" → "ml"). Solo retorna unidad si
# todas las variantes detectadas comparten misma unidad.
_BOT_VARIANT_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(ml|gr?|g|gramos?|kg|oz|l|lts?)",
    re.IGNORECASE,
)


def _detect_common_variant_unit(outbound_text: str) -> Optional[str]:
    """Retorna la unidad común si el bot ofreció variantes con SOLO una unidad."""
    if not outbound_text:
        return None
    units_found = set()
    for m in _BOT_VARIANT_UNIT_RE.finditer(outbound_text):
        u = m.group(1).lower()
        # Normalizar a singular ml/g/kg/oz/l.
        if u in ("gr", "gramos", "gramo"):
            u = "g"
        elif u in ("kilogramos", "kilogramo"):
            u = "kg"
        elif u in ("onzas", "onza"):
            u = "oz"
        elif u in ("litros", "litro", "lts", "lt"):
            u = "l"
        units_found.add(u)
    if len(units_found) == 1:
        return units_found.pop()
    return None


# Detectar producto + variantes ofrecidas en el ÚLTIMO outbound del bot:
#   "Para el *Sérum de Vitamina C*, tenemos dos presentaciones:
#    * 30ml por $85.000 COP
#    * 15ml por $52.000 COP"
_BOT_OFFERED_VARIANTS_PATTERN = re.compile(
    # Cubre 3 variantes comunes en español:
    #   • "Para el *Producto X*, tenemos..."
    #   • "El *Producto X* lo/la tenemos en..."
    #   • "Del *Producto X* tenemos..."
    r"\b(?:para\s+(?:el|la|los|las|tu)|del?|el|la|los|las)\s+\*?"
    r"([A-ZÁÉÍÓÚÑa-záéíóúñ][^*\n.]{2,60}?)"
    r"\*?[,.:]?\s+"
    r"(?:(?:lo|la|los|las)\s+tenemos|tenemos|prefieres|cuál|"
    r"qu[eé]\s+presentaci[oó]n)",
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
    # 2. ¿El último outbound del bot presentó variantes?
    #    (Necesitamos esto ANTES para extraer la unidad común como fallback.)
    last_bot_outbound = None
    for msg in reversed(history or []):
        if (msg.get("direction") or "").lower() == "outbound":
            last_bot_outbound = str(msg.get("content") or "")
            break
    if not last_bot_outbound:
        return None
    if not _bot_outbound_contains_variant_options(last_bot_outbound):
        return None

    # 3. ¿Inbound del cliente es respuesta corta de variante?
    #    Si dijo solo número (e.g. "30" o "Dame el de 30"), usamos la unidad
    #    común del último outbound del bot como fallback (e.g. "ml" si las
    #    opciones eran "15ml/30ml").
    fallback_unit = _detect_common_variant_unit(last_bot_outbound)
    client_variant = _extract_client_variant(
        inbound_text, fallback_unit=fallback_unit,
    )
    if not client_variant:
        return None

    # 4. ¿Qué producto se discute?
    product_hint = _extract_product_from_bot_question(last_bot_outbound)
    if not product_hint:
        return None

    # 5. Resolver en catalog.
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
