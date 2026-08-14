"""Parsing de texto y formato de respuestas del cotizador de envíos (extraído de
tools/shipping_quote_tool.py — G12). Funciones puras (string in/out, sin I/O).
Extraído verbatim 2026-08-13 — comportamiento idéntico.
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from text_utils import normalize_text as _normalize_text  # noqa: F401
from tools.catalog_contract import variant_label  # ADR-0029: label canónico único
from tools.shipping_models import PackageEstimate  # noqa: F401 (anotaciones)

logger = logging.getLogger("orchestrator.tools.shipping_text")

_PRODUCT_TITLE_STOPWORDS = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "y",
    "para",
    "con",
    "sin",
    "en",
}


def _tokenize_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.isdigit():
            return int(cleaned)
    return None


def _extract_weight_kg(text: str) -> Optional[float]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    kg_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|kilo|kilos)", normalized)
    if kg_match:
        value = _safe_float(kg_match.group(1))
        if value and value > 0:
            return value

    g_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(g|gr|gramo|gramos)", normalized)
    if g_match:
        value = _safe_float(g_match.group(1))
        if value and value > 0:
            return max(value / 1000.0, 0.05)

    return None


def _extract_requested_quantity(text: str) -> int:
    normalized = _normalize_text(text)
    if not normalized:
        return 1

    patterns = [
        r"\bx\s*(\d{1,3})\b",  # x2
        r"\b(\d{1,3})\s*x\b",  # 2x
        r"\b(\d{1,3})\s*(?:unidad|unidades|ud|uds|u)\b",
        r"\bpara\s+(\d{1,3})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        qty = _safe_int(match.group(1))
        if qty and qty > 0:
            return min(qty, 200)

    # Fallback: si el mensaje es corto (ej: "3", "quiero 3"), o al menos no contiene indicadores de dirección:
    if len(normalized) < 15 and not re.search(r"calle|cra|carrera|sur|norte", normalized):
        generic = re.search(r"\b(\d{1,3})\b", normalized)
        if generic:
            qty = _safe_int(generic.group(1))
            if qty and qty > 0:
                return min(qty, 200)

    return 1


def _sanitize_dane_code(raw: object) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 8 and digits.endswith("000"):
        return digits[:5]
    if len(digits) == 5:
        return digits
    return ""


def _normalize_country_code(raw: object, default: str = "CO") -> str:
    ascii_country = unicodedata.normalize("NFKD", str(raw or "")).encode("ascii", "ignore").decode("ascii")
    token = re.sub(r"[^A-Za-z]", "", ascii_country).upper()
    if not token:
        return default
    if token in {"CO", "COL", "COLOMBIA"}:
        return "CO"
    if len(token) == 2:
        return token
    return token


def _product_title_tokens(title: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_text(title))
        if len(token) >= 3 and token not in _PRODUCT_TITLE_STOPWORDS
    }


def _variation_label(variation: dict) -> str:
    """Etiqueta legible de una variante. ADR-0029 F2: delega en el label CANÓNICO
    compartido (tools.catalog_contract.variant_label) — única fórmula cross-surface."""
    return variant_label(variation.get("attributes"), variation.get("sku"))


def _clean_product_title(title: str) -> str:
    """Elimina prefijos de ambiente como [TEST], [DEMO], [STAGING] del título del producto."""
    return re.sub(r"^\[.*?\]\s*", "", str(title or "")).strip()


def _build_product_disambiguation_text(product_titles: list[str]) -> str:
    clean_titles = [_clean_product_title(t) for t in product_titles if t and t.strip()]
    clean_titles = [t for t in clean_titles if t]  # filtrar vacíos post-limpieza
    if not clean_titles:
        return "Para cotizar envío necesito confirmar el producto exacto. ¿Cuál deseas?"
    options = " / ".join(clean_titles[:3])
    return (
        f"Para cotizar envío con precisión, confirma el producto: {options}. "
        "Con eso te paso de inmediato la opción más económica y la más rápida."
    )


def _extract_quantity_near_phrase(norm_text: str, phrase_tokens: list[str]) -> int:
    """Busca un número justo antes (o muy cerca) de cualquiera de los tokens del
    nombre del producto. Ej: '2 aceites de coco virgen' con tokens incluyendo
    'aceite' o 'coco' → 2.
    """
    if not phrase_tokens:
        return 0
    sig_tokens = [t for t in phrase_tokens if len(t) > 3]
    if not sig_tokens:
        sig_tokens = phrase_tokens
    pattern = (
        r"(\d+)\s+(?:[a-zñáéíóú]+s?\s+){0,3}("
        + "|".join(re.escape(t) for t in sig_tokens)
        + r")"
    )
    m = re.search(pattern, norm_text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def _format_money(value: object, currency: str = "COP") -> str:
    amount = _safe_float(value)
    if amount is None:
        return "N/D"
    if currency.upper() == "COP":
        return f"${int(round(amount)):,.0f}".replace(",", ".")
    return f"{amount:.2f} {currency.upper()}"


def _format_eta(rate: dict) -> str:
    delivery_date = str(rate.get("delivery_date") or "").strip()
    if delivery_date:
        try:
            dt = datetime.fromisoformat(delivery_date.replace("Z", "+00:00"))
            # Convertir a hora Colombia (America/Bogota = UTC-5 fijo, sin DST)
            # Usamos timedelta en lugar de zoneinfo para no requerir dependencia extra.
            from datetime import timedelta
            BOGOTA_OFFSET = timedelta(hours=-5)
            dt_bogota = dt.astimezone(timezone(BOGOTA_OFFSET))
            return dt_bogota.strftime("%d/%m/%Y")
        except (ValueError, Exception):
            return delivery_date

    estimate = str(rate.get("delivery_estimate") or "").strip()
    if estimate:
        return estimate
    return "N/D"


def _format_rate_line(label: str, rate: dict) -> str:
    carrier = str(rate.get("carrier") or "carrier").strip()
    service = str(rate.get("service") or "servicio").strip()
    # Deduplicar si el nombre del carrier aparece al inicio del service name
    # Ej: carrier='Deprisa', service='Deprisa Estandar' -> mostramos solo 'Deprisa Estandar'
    if service.lower().startswith(carrier.lower()):
        carrier_info = service
    else:
        carrier_info = f"{carrier} {service}"
    currency = str(rate.get("currency") or "COP")
    price_info = _format_money(rate.get("total_price"), currency)
    if not price_info:
        price_info = "Pendiente"
    eta = _format_eta(rate)
    return f"• *{label}*: {carrier_info} | {price_info} | entrega {eta}"


def _fmt_weight(kg: float) -> str:
    """Formato legible para peso: evita decimales innecesarios y separadores de miles."""
    if kg >= 1:
        return f"{int(kg)} kg" if kg == int(kg) else f"{kg:.1f} kg"
    grams = kg * 1000
    return f"{int(grams)} g" if grams == int(grams) else f"{grams:.0f} g"


def _fmt_dim(cm: float) -> str:
    """Formato sin decimales innecesarios para dimensiones."""
    return str(int(cm)) if cm == int(cm) else f"{cm:.1f}"


def _format_package_context_line(package: PackageEstimate) -> str:
    """Línea interna de log — no se expone al cliente en la respuesta principal."""
    l, w, h = _fmt_dim(package.length_cm), _fmt_dim(package.width_cm), _fmt_dim(package.height_cm)
    qty_label = "1 unidad" if package.quantity == 1 else f"{package.quantity} unidades"
    summary = f"{qty_label}, {_fmt_weight(package.weight_kg)}, {l}\u00d7{w}\u00d7{h} cm"
    if package.product_title:
        summary += f" | {package.product_title}"
    if package.variant_label and package.variant_label.strip().lower() not in {"estandar", "estándar", ""}:
        summary += f" ({package.variant_label})"
    return summary


def _build_quote_response_text(
    origin: dict,
    destination: dict,
    highlights: dict,
    package: PackageEstimate,
) -> Optional[str]:
    cheapest = highlights.get("cheapest") if isinstance(highlights, dict) else None
    fastest = highlights.get("fastest") if isinstance(highlights, dict) else None
    if not isinstance(cheapest, dict):
        return None

    destination_city = str(destination.get("city") or "tu ciudad")
    qty_label = "1 unidad" if package.quantity == 1 else f"{package.quantity} unidades"
    product_label = ""
    if package.product_title:
        product_label = f" de {package.product_title}"
        if package.variant_label and package.variant_label.strip().lower() not in {"estandar", "estándar", ""}:
            product_label += f" ({package.variant_label})"

    # Multi-producto: header con lista de items con bullets para legibilidad.
    if package.source == "multi":
        items_text = package.product_title or ""
        # product_title viene como "2x A + 1x B + 1x C" — convertir a bullets.
        if " + " in items_text:
            items_lines = "\n".join(f"• {item.strip()}" for item in items_text.split(" + "))
        else:
            items_lines = f"• {items_text}" if items_text else ""
        header = (
            f"Envío de tu pedido ({package.quantity} unidades) a {destination_city}:\n"
            f"{items_lines}"
        )
    else:
        header = f"Envío de {qty_label}{product_label} a {destination_city}:"
    cheapest_line = _format_rate_line("Económica", cheapest)
    lines = [header, cheapest_line]

    if isinstance(fastest, dict):
        same_eta = _format_eta(fastest) == _format_eta(cheapest)
        same = (
            str(fastest.get("carrier") or "") == str(cheapest.get("carrier") or "")
            and str(fastest.get("service") or "") == str(cheapest.get("service") or "")
            and str(fastest.get("total_price") or "") == str(cheapest.get("total_price") or "")
        )
        if not same and not same_eta:
            lines.append(_format_rate_line("Rápida", fastest))
        # Si es la misma opción o la fecha de entrega es idéntica, no agregar línea redundante

    # Solo preguntar por elección si realmente hay 2 opciones distintas
    has_fast_option = len(lines) > 2  # header + cheapest + fastest
    if has_fast_option:
        lines.append("¿Con cuál continuamos? (*Económica* o *Rápida*)")
    else:
        lines.append("¿Continuamos con la opción *Económica*?")

    # Detalle técnico del paquete solo en log — no al cliente
    logger.info("[SHIPPING_QUOTE] Paquete estimado: %s", _format_package_context_line(package))
    # Párrafos WhatsApp: \n\n entre secciones para respiro visual
    paragraph = "\n\n"
    body = "\n".join(lines[1:-1]).strip()
    question = str(lines[-1]).strip()
    return paragraph.join([lines[0], body, question])
