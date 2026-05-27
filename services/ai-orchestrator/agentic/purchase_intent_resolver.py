"""Pre-LLM resolver determinístico: intent de compra multi-producto.

Bug runtime KAIU 2026-05-24 conv 98212532 turn 2:
  Cliente: "Necesito 3 jabones de coco de 100g y un sérum hialurónico"
  Gemini con tools → STOP+empty (saturación SDK con 19 tools + prompt grande).
  Text-only retry recupera texto afirmando "Agregando 3 jabones..." pero
  SIN poder llamar tools → CartStateInvariant Case A → rewrite genérico.
  UX rota: cliente NO debe sufrir Gemini SDK quirks para casos comunes.

Solución arquitectónica: cuando el cliente inicia con un pedido CLARO
(producto identificable en catalog + cantidad + variante específica),
bypaseamos Gemini y resolvemos directamente con add_to_cart.

Cubre casos típicos:
  • "Necesito 3 jabones de coco de 100g"
  • "Quiero un sérum de vitamina C de 15ml"
  • "Dame 2 aceites de almendras"
  • "Llévame 1 jabón coco 100g y 2 jabones lavanda 150g"

Cuando un ítem es ambiguo (producto sin variante + producto tiene >1
variantes), el resolver agrega los ítems claros + delega a Gemini con
una marca explícita "ya agregamos X, pregunta variante para Y".

NO usa LLM — pura lógica determinística (regex + catalog lookup).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Verbos de intent de compra ("quiero", "necesito", etc.)
_PURCHASE_INTENT_VERBS = (
    "quiero", "necesito", "llevame", "llévame", "dame", "envíame",
    "envia", "envíate", "agregame", "agrégame", "sumame", "súmame",
    "pidame", "pídeme", "manda", "mandame", "mándame",
)
_INTENT_VERB_RE = re.compile(
    r"\b(?:" + "|".join(_PURCHASE_INTENT_VERBS) + r")\b",
    re.IGNORECASE,
)

# Cuantificador: número o palabra ("3", "un", "una", "dos", "tres", ...).
_QTY_WORDS = {
    "un": 1, "una": 1, "unos": 1, "unas": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}

# Variante: número + unidad de presentación (ml, g, gramos, kg, oz, L).
_VARIANT_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ml|gr?|g|gramos?|kg|kilogramos?|oz|onzas?|l|lts?|litros?)\b",
    re.IGNORECASE,
)


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", _strip_diacritics(s).lower()).strip()


def _normalize_variant_unit(value: str, unit: str) -> str:
    unit_lower = unit.lower().strip()
    if unit_lower in ("gramos", "gramo", "gr"):
        unit_lower = "g"
    if unit_lower in ("kilogramos", "kilogramo", "kg"):
        unit_lower = "kg"
    if unit_lower in ("onzas", "onza"):
        unit_lower = "oz"
    if unit_lower in ("litros", "litro", "lts", "lt"):
        unit_lower = "l"
    try:
        n = float(value.replace(",", "."))
        if n.is_integer():
            value = str(int(n))
    except ValueError:
        pass
    return f"{value}{unit_lower}"


# Conectores que delimitan items separados ("y", ",", "+").
_ITEM_SEPARATORS = re.compile(r"\s*(?:,|;|\+|\sy\s|\se\s|\s&\s)\s*", re.IGNORECASE)


def _split_into_items(text: str) -> list[str]:
    """Divide el inbound en items individuales por conectores ('y', ',')."""
    # Strip leading verb of intent.
    cleaned = _INTENT_VERB_RE.sub("", text, count=1).strip(" ,.;")
    parts = _ITEM_SEPARATORS.split(cleaned)
    return [p.strip(" ,.;") for p in parts if p and p.strip()]


def _parse_qty_at_start(item: str) -> tuple[int, str]:
    """Extrae cantidad inicial de un item ('3 jabones...' → (3, 'jabones...')).
    Si no hay cantidad, retorna (1, item) — interpretamos default 1.
    """
    item = item.strip()
    # Numérico explícito.
    m = re.match(r"^(\d+)\s+(.+)$", item)
    if m:
        try:
            return (int(m.group(1)), m.group(2).strip())
        except ValueError:
            pass
    # Palabra.
    m = re.match(r"^([a-záéíóúñ]+)\s+(.+)$", item, re.IGNORECASE)
    if m:
        w = _normalize(m.group(1))
        if w in _QTY_WORDS:
            return (_QTY_WORDS[w], m.group(2).strip())
    return (1, item)


def _extract_variant_label(item: str) -> tuple[Optional[str], str]:
    """Extrae label de variante si está presente.
    Returns: (variant_label or None, item_sin_variant_substring)
    """
    m = _VARIANT_UNIT_RE.search(item)
    if not m:
        return (None, item)
    label = _normalize_variant_unit(m.group(1), m.group(2))
    # Remove the matched variant + opcional "de" prefix from item title.
    item_clean = item[:m.start()] + item[m.end():]
    item_clean = re.sub(r"\s+de\s+$", "", item_clean.strip(), flags=re.IGNORECASE)
    item_clean = re.sub(r"\s+", " ", item_clean).strip(" ,.;")
    return (label, item_clean)


# Stop-words que NO son parte del nombre del producto.
_STOP_WORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una",
    "al", "a", "con", "para", "y", "e",
}

# Rev. 108 (founder UAT 2026-05-27 — "jabón de chocolate" matcheó "Jabón
# de Coco"): cuando el cliente menciona solo un nombre de categoría, el
# matcher debe rechazar si NINGÚN otro token específico matchea. Tokens
# de categoría NO bastan para identificar un producto único.
_CATEGORY_TOKENS = {
    "jabon", "jabones", "serum", "serums", "aceite", "aceites",
    "kit", "kits", "shampoo", "champu", "crema", "cremas",
    "esencial", "esenciales", "artesanal", "artesanales",
    "vegetal", "vegetales", "natural", "naturales",
}


def _token_matches(ht: str, tt: str) -> bool:
    """Match flexible entre tokens, evitando falsos positivos con chars cortos.

    Bug runtime 2026-05-24 ("sérum hialurónico" matcheó Vit C):
      `"c" in "hialuronico"` → True (`tt in ht`). Esto generaba empates
      espurios cuando un title tiene tokens de 1 char (e.g. "C" en "Vit C").
    Fix: substring match SOLO cuando ambos tokens tienen len ≥ 4. Si
    alguno es corto, solo aceptamos == exacto.
    """
    if not ht or not tt:
        return False
    if ht == tt:
        return True
    if len(ht) < 4 or len(tt) < 4:
        return False
    return ht in tt or tt in ht


def _find_product_in_catalog(
    name_hint: str, catalog: list[dict],
) -> Optional[dict]:
    """Busca un producto cuyo título matchee `name_hint` por palabras-clave.

    Algoritmo: tokenize hint → remueve stop-words → cuenta cuántos tokens
    del hint aparecen en cada título. El producto con mayor score (≥2
    tokens matched, o 1 si título tiene 2-3 palabras) gana. Empate → None.
    """
    if not name_hint or not catalog:
        return None
    hint_tokens = [
        t for t in re.split(r"\W+", _normalize(name_hint))
        if t and t not in _STOP_WORDS and len(t) >= 3
    ]
    if not hint_tokens:
        return None

    best: list[tuple[int, dict]] = []
    for prod in catalog:
        title = _normalize(str(prod.get("title") or ""))
        if not title:
            continue
        title_tokens = [
            t for t in re.split(r"\W+", title)
            if t and t not in _STOP_WORDS
        ]
        score = sum(
            1 for ht in hint_tokens
            if any(_token_matches(ht, tt) for tt in title_tokens)
        )
        if score == 0:
            continue
        best.append((score, prod))

    if not best:
        return None
    best.sort(key=lambda x: -x[0])
    top_score = best[0][0]
    top_matches = [p for s, p in best if s == top_score]

    # Rev. 108 (founder UAT 2026-05-27) — Anti falso-positivo de categoría:
    # si el cliente solo mencionó tokens de categoría (jabon, serum, etc)
    # SIN ningún token específico (chocolate, lavanda, vitamina, etc),
    # los matches son por categoría y NO identifican un producto único.
    # NO retornar — el LLM debe pedir clarificación.
    non_category_hint_tokens = [
        t for t in hint_tokens if t not in _CATEGORY_TOKENS
    ]
    if not non_category_hint_tokens:
        return None  # Cliente solo dijo categoría → no es match único.

    # Verificar que el score venga de tokens específicos, no solo categoría.
    # Si TODO el score viene de tokens categoría, no es match real.
    if len(top_matches) > 1:
        # Multiple matches con mismo score — peligroso. Solo retornar si
        # el match incluye al menos un token NO-categoría.
        for prod in top_matches:
            title = _normalize(str(prod.get("title") or ""))
            title_tokens = [
                t for t in re.split(r"\W+", title)
                if t and t not in _STOP_WORDS
            ]
            specific_matched = any(
                _token_matches(ht, tt)
                for ht in non_category_hint_tokens
                for tt in title_tokens
            )
            if specific_matched:
                return prod  # Solo retornar el que tiene match específico
        return None  # Ningún top_match tiene match específico → ambiguo real

    return top_matches[0]


def _find_variation_by_label(
    product: dict, label: str,
) -> Optional[dict]:
    """Match flexible '15ml' ↔ '15 ml' ↔ '15 mililitros' en variants."""
    target = re.sub(r"\s+", "", _normalize(label))
    for v in (product.get("variants") or []):
        v_label = re.sub(r"\s+", "", _normalize(str(v.get("label") or "")))
        if v_label == target:
            return v
    return None


# ─── Output schema ──────────────────────────────────────────────────────

# Un item resuelto = tupla product_id + variation_id + qty + metadata.
ResolvedItem = dict  # {"product_id", "variation_id", "title", "label", "qty", "unit_price_cop"}

# Un item ambiguo = producto identificado pero variante no.
AmbiguousItem = dict  # {"product_title", "product_id", "qty", "available_variants": [...]}


def try_resolve_purchase_intent(
    *,
    inbound_text: str,
    catalog: list[dict],
) -> Optional[dict]:
    """Intenta resolver un inbound de compra inicial determinísticamente.

    Returns:
      None si NO aplica (no es intent de compra claro, productos no
      encontrados, demasiado ambiguo).

      Si aplica, retorna dict:
        {
          "resolved": [ResolvedItem, ...],     # listos para add_to_cart
          "ambiguous": [AmbiguousItem, ...],   # producto OK pero variante ambigua
        }

      El caller agrega resolved + presenta variantes para ambiguous.
    """
    if not inbound_text or not catalog:
        return None
    if not _INTENT_VERB_RE.search(inbound_text):
        return None
    # Demasiado largo → mejor delegar a Gemini (contexto adicional).
    if len(inbound_text) > 300:
        return None

    items = _split_into_items(inbound_text)
    if not items:
        return None

    resolved: list[ResolvedItem] = []
    ambiguous: list[AmbiguousItem] = []

    for item in items:
        qty, rest = _parse_qty_at_start(item)
        if qty < 1 or qty > 50:
            return None  # Algo raro, mejor abortar a Gemini.
        variant_label, name_hint = _extract_variant_label(rest)
        if not name_hint:
            return None
        product = _find_product_in_catalog(name_hint, catalog)
        if not product:
            # Algún item no se identifica → abortar a Gemini para que
            # maneje (puede ser pregunta general, no compra clara).
            return None
        variants = product.get("variants") or []
        if not variants:
            return None  # Producto sin variantes — caso edge, delegar.

        if variant_label:
            v = _find_variation_by_label(product, variant_label)
            if not v:
                # Variante mencionada pero no existe — delegar a Gemini.
                return None
            price = float(v.get("price") or 0)
            if price <= 0:
                return None
            resolved.append({
                "product_id": str(product.get("id") or ""),
                "variation_id": str(v.get("id") or ""),
                "title": str(product.get("title") or ""),
                "label": str(v.get("label") or ""),
                "qty": qty,
                "unit_price_cop": price,
            })
        else:
            # Sin variante explícita.
            if len(variants) == 1:
                # Producto con UNA sola variante — asumimos esa.
                v = variants[0]
                price = float(v.get("price") or 0)
                resolved.append({
                    "product_id": str(product.get("id") or ""),
                    "variation_id": str(v.get("id") or ""),
                    "title": str(product.get("title") or ""),
                    "label": str(v.get("label") or ""),
                    "qty": qty,
                    "unit_price_cop": price,
                })
            else:
                # Múltiples variantes — ambiguo, bot pregunta.
                ambiguous.append({
                    "product_id": str(product.get("id") or ""),
                    "product_title": str(product.get("title") or ""),
                    "qty": qty,
                    "available_variants": [
                        {
                            "id": str(v.get("id") or ""),
                            "label": str(v.get("label") or ""),
                            "price_cop": float(v.get("price") or 0),
                        }
                        for v in variants
                    ],
                })

    if not resolved and not ambiguous:
        return None
    return {"resolved": resolved, "ambiguous": ambiguous}


def compose_outbound_from_resolution(
    resolution: dict,
    *,
    customer_name: Optional[str] = None,
) -> str:
    """Compone outbound natural en formato WhatsApp del bot tras resolver.

    Cubre 3 casos:
      • Solo resolved → "Listo, agregué N, M. ¿Sumamos algo más o envío?"
      • Solo ambiguous → "Para X, ¿prefieres Yml o Zml?"
      • Mix → "Agregué N. Para X, ¿prefieres Yml o Zml?"
    """
    resolved = resolution.get("resolved") or []
    ambiguous = resolution.get("ambiguous") or []

    greeting = f"Listo, {customer_name}. " if customer_name else "Listo. "
    parts: list[str] = []

    if resolved:
        # Bullet list de items agregados.
        bullets = []
        for r in resolved:
            label = r.get("label") or ""
            label_str = f" de {label}" if label else ""
            bullets.append(
                f"* {r['qty']} *{r['title']}*{label_str}"
            )
        added_text = (
            f"{greeting}Agregué a tu carrito:\n\n" + "\n".join(bullets)
        )
        parts.append(added_text)

    if ambiguous:
        for amb in ambiguous:
            variant_lines = []
            for v in amb["available_variants"]:
                price = int(v["price_cop"])
                price_str = f"${price:,}".replace(",", ".")
                variant_lines.append(f"* {v['label']} por *{price_str} COP*")
            ask = (
                f"Para *{amb['product_title']}*, tenemos estas "
                f"presentaciones:\n\n" + "\n".join(variant_lines) +
                "\n\nCuál te gustaría llevar?"
            )
            parts.append(ask)
    else:
        # No ambiguous → cerrar con CTA siguiente paso (envío).
        if resolved:
            parts.append(
                "Sumamos algo más al pedido o ya coordinamos el envío? "
                "Dime a qué ciudad lo enviamos."
            )

    return "\n\n".join(parts)
