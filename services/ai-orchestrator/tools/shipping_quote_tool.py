import logging
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import jwt
from supabase import Client

logger = logging.getLogger("orchestrator.tools.shipping_quote")

API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

DEFAULT_WEIGHT_KG = float(os.getenv("INBOX_SHIPPING_DEFAULT_WEIGHT_KG", "1"))
DEFAULT_LENGTH_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_LENGTH_CM", "10"))
DEFAULT_WIDTH_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_WIDTH_CM", "10"))
DEFAULT_HEIGHT_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_HEIGHT_CM", "10"))
SHIPPING_REQUEST_TIMEOUT_SECONDS = float(os.getenv("INBOX_SHIPPING_TIMEOUT_SECONDS", "25"))

_SHIPPING_SUBJECT_TOKENS = {
    "envio",
    "enviar",
    "domicilio",
    "flete",
    "entrega",
}
_SHIPPING_QUOTE_TOKENS = {
    "cuanto",
    "cuanta",
    "vale",
    "valdria",
    "valor",
    "costo",
    "coste",
    "precio",
    "tarifa",
    "tarifas",
    "cotizar",
    "cotizas",
    "cotizacion",
    "cotiza",
    "cobran",
    "cobras",
}
_SHIPPING_NON_QUOTE_TOKENS = {
    "tracking",
    "rastrear",
    "rastreo",
    "seguimiento",
    "guia",
    "estado",
}
_SHIPPING_FOLLOWUP_PROMPT_MARKERS = (
    # Frases determinísticas generadas por el tool
    "para cotizar envio necesito tu ciudad",
    "comparteme departamento y ciudad",
    "indica tambien el departamento",
    "para cotizar envio con precision, confirma el producto",
    "para cotizar envio necesito confirmar el producto exacto",
    "necesito tu ciudad de entrega",
    # Frases que el LLM genera libremente al pedir ciudad de entrega en contexto de envío
    "ciudad de destino",     # "ciudad de destino"
    "ciudad del envio",      # "ciudad del envío"
    # Frases de ofrecimiento de cotización por parte del bot
    "deseas que te cotice",
    "quieres que te cotice",
    "te cotice el envio",
    "cotice el envio",
)
_DANE_SOURCE_FILE = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "dane-colombia.ts"
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


@dataclass
class ShippingQuoteResult:
    handled: bool
    response_text: Optional[str] = None
    requires_human: bool = False


@dataclass
class PackageEstimate:
    weight_kg: float
    length_cm: float
    width_cm: float
    height_cm: float
    quantity: int
    product_title: Optional[str] = None
    variant_label: Optional[str] = None
    source: str = "default"


@dataclass
class PackageEstimateDecision:
    package: Optional[PackageEstimate] = None
    ambiguous_product_titles: list[str] = field(default_factory=list)


from text_utils import normalize_text as _normalize_text, normalize_phone as _normalize_phone  # noqa: E402


def _tokenize_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


@lru_cache(maxsize=1)
def _load_city_index() -> dict[str, list[dict[str, str]]]:
    """
    Carga índice de municipios CO desde apps/web/lib/dane-colombia.ts.
    Estructura: { city_normalized: [{city, state, dane_code}, ...] }.
    """
    if not _DANE_SOURCE_FILE.exists():
        logger.warning("No se encontró catálogo DANE en %s", _DANE_SOURCE_FILE)
        return {}

    try:
        source = _DANE_SOURCE_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("No se pudo leer catálogo DANE: %s", exc)
        return {}

    city_index: dict[str, list[dict[str, str]]] = {}
    dept_pattern = re.compile(
        r"\{\s*codigo:\s*'(?P<dep_code>\d+)'\s*,\s*nombre:\s*'(?P<dep_name>[^']+)'\s*,\s*municipios:\s*\[(?P<munis>.*?)\]\s*,?\s*\}",
        re.DOTALL,
    )
    muni_pattern = re.compile(
        r"\{\s*codigo:\s*'(?P<code>\d{5})'\s*,\s*nombre:\s*'(?P<name>[^']+)'\s*\}"
    )

    for dep in dept_pattern.finditer(source):
        dept_name = dep.group("dep_name").strip()
        munis_blob = dep.group("munis")
        for muni in muni_pattern.finditer(munis_blob):
            city_name = muni.group("name").strip()
            dane_code = muni.group("code")
            city_norm = _normalize_text(city_name)
            
            aliases = [city_norm]
            if " d.c." in city_norm:
                aliases.append(city_norm.replace(" d.c.", ""))
            if " (distrito capital)" in city_norm:
                aliases.append(city_norm.replace(" (distrito capital)", ""))
            if "bogota" in city_norm:
                aliases.append("bogota") # Catch-all por si las dudas
                
            for alias in set(aliases):
                city_index.setdefault(alias, []).append(
                    {
                        "city": city_name,
                        "state": dept_name,
                        "dane_code": dane_code,
                    }
                )

    return city_index


@lru_cache(maxsize=1)
def _city_names_by_length_desc() -> list[str]:
    return sorted(_load_city_index().keys(), key=len, reverse=True)


def _find_city_entries_in_text(normalized_query: str) -> list[dict[str, str]]:
    city_index = _load_city_index()
    if not city_index or not normalized_query:
        return []

    matches: list[dict[str, str]] = []
    for city_norm in _city_names_by_length_desc():
        if len(city_norm) < 3:
            continue
        pattern = rf"(^|\b){re.escape(city_norm)}(\b|$)"
        if not re.search(pattern, normalized_query):
            continue
        entries = city_index.get(city_norm, [])
        if not entries:
            continue
        matches.extend(entries)
        # El match más largo suele ser suficiente para destino conversacional.
        break
    return matches


def _destination_from_city_entry(entry: dict[str, str]) -> dict[str, str]:
    return {
        "city": entry["city"],
        "state": entry["state"],
        "country": "CO",
        "postalCode": entry["dane_code"],
        "dane_code": entry["dane_code"],
    }


def _resolve_destination_from_query(query_text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Intenta resolver destino desde texto libre.
    Retorna:
    - (destination, None) si resolvió
    - (None, city_name) si ciudad detectada pero ambigua (requiere depto)
    - (None, None) si no pudo resolver ciudad
    """
    normalized_query = _normalize_text(query_text)
    entries = _find_city_entries_in_text(normalized_query)
    if not entries:
        return None, None

    # Deduplicar por dane_code (en caso de alias redundantes)
    unique_dane = {}
    for e in entries:
        unique_dane[e["dane_code"]] = e
    entries = list(unique_dane.values())

    if len(entries) == 1:
        return _destination_from_city_entry(entries[0]), None

    # Si la ciudad aparece en múltiples departamentos, intentar desambiguar
    # por departamento mencionado explícitamente en el mensaje.
    narrowed = []
    for entry in entries:
        state_norm = _normalize_text(entry["state"])
        if state_norm and state_norm in normalized_query:
            narrowed.append(entry)

    if len(narrowed) == 1:
        return _destination_from_city_entry(narrowed[0]), None

    return None, entries[0]["city"]


def is_shipping_quote_query(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    tokens = _tokenize_words(normalized)
    if not tokens:
        return False

    shipping_mentioned = bool(tokens & _SHIPPING_SUBJECT_TOKENS) or "cuanto cuesta enviar" in normalized
    if not shipping_mentioned:
        return False

    has_quote_signal = bool(tokens & _SHIPPING_QUOTE_TOKENS) or "cuanto cuesta enviar" in normalized
    if "cotiz" in normalized and shipping_mentioned:
        has_quote_signal = True
    if "cuanto vale" in normalized and "envio" in normalized:
        has_quote_signal = True
    if "cuanto cobran" in normalized and ({"envio", "domicilio", "flete"} & tokens):
        has_quote_signal = True

    # Evitar disparar cotización en frases de tracking/estado que se resuelven por otro intent.
    if (tokens & _SHIPPING_NON_QUOTE_TOKENS) and not has_quote_signal:
        return False

    # NUEVO: ciudad válida + token de envío sin precio explícito = intención implícita de cotización
    # Cubre frases como "Envíos a Medellín?", "¿Hacen domicilios a Cali?"
    if shipping_mentioned and not has_quote_signal:
        normalized_q = _normalize_text(text)
        if _find_city_entries_in_text(normalized_q):
            logger.info(
                "[SHIPPING_QUOTE] Intent inferido por ciudad + envío sin precio explícito | query=%s",
                text[:80],
            )
            return True

    return has_quote_signal


def _get_recent_conversation_messages(
    supabase: Client,
    conversation_id: str,
    limit: int = 8,
) -> list[dict]:
    res = (
        supabase.table("messages")
        .select("direction, content, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _is_shipping_followup_query(query_text: str, recent_messages: list[dict]) -> bool:
    if is_shipping_quote_query(query_text):
        return True

    normalized_query = _normalize_text(query_text)
    if not normalized_query:
        return False

    # Consulta corta tipo "Costo a Medellin?" suele omitir la palabra "envio"
    # pero en contexto conversacional implica cotización de flete.
    tokens = _tokenize_words(normalized_query)
    has_quote_signal = bool(set(tokens) & _SHIPPING_QUOTE_TOKENS)
    has_non_quote_signal = bool(set(tokens) & _SHIPPING_NON_QUOTE_TOKENS)
    has_city_hint = bool(_find_city_entries_in_text(normalized_query))
    if has_quote_signal and has_city_hint and not has_non_quote_signal and len(tokens) <= 6:
        logger.info(
            "[SHIPPING_QUOTE] Intent inferred by short city+cost pattern | query=%s",
            query_text[:120],
        )
        return True

    last_outbound = next(
        (
            msg for msg in recent_messages
            if str(msg.get("direction") or "").strip().lower() == "outbound"
        ),
        None,
    )
    if not last_outbound:
        return False

    outbound_text = _normalize_text(str(last_outbound.get("content") or ""))
    
    # Evitar interceptar como "shipping followup" si el bot acaba de pedir
    # datos personales/dirección (FSM de cierre de compra).
    personal_data_markers = [
        "tu nombre", "tu nombre completo", "indicanos tu nombre", "cual es tu nombre",
        "direccion de entrega", "tu direccion", "direccion exacta", "esta direccion",
        "se encuentra esta direccion", "correo electronico", "barrio", "torre", "apartamento"
    ]
    if any(m in outbound_text for m in personal_data_markers):
        return False

    has_separator = "/" in query_text or "," in query_text
    shipping_context_tokens = {"envio", "cotizar", "cotice", "costo", "flete", "despacho", "domicilio", "delivery"}
    marker_matched = any(marker in outbound_text for marker in _SHIPPING_FOLLOWUP_PROMPT_MARKERS)
    has_shipping_context = bool(_tokenize_words(outbound_text) & shipping_context_tokens)
    if marker_matched:
        if not has_shipping_context:
            return False
        logger.info(
            "[SHIPPING_QUOTE] Followup por marker | last_outbound=%s | query=%s",
            outbound_text[:80], query_text[:60],
        )
        return has_city_hint or has_separator or len(tokens) <= 4

    # Respuesta afirmativa simple a ofrecimiento de cotización por parte del bot.
    # SOLO se activa cuando el ÚLTIMO outbound del bot contiene contexto de envío activo
    # (pidiendo ciudad, ofreciendo cotizar, etc.). Si el último outbound ya mostró una
    # tarifa concreta (contiene líneas de rate), NO interceptamos — dejamos que el LLM
    # avance el FSM de venta.
    _AFFIRMATIVE_SHIPPING_REPLY = {"si", "sí", "ok", "dale", "claro", "perfecto", "listo", "procede"}
    if len(tokens) <= 2 and (tokens & _AFFIRMATIVE_SHIPPING_REPLY):
        if not last_outbound:
            return False
        last_outbound_norm = _normalize_text(str(last_outbound.get("content") or ""))
        # Si el bot ya mostró una tarifa concreta y está esperando confirmación de opción,
        # NO interceptamos. El LLM debe avanzar al siguiente paso del FSM.
        if "economica" in last_outbound_norm or "rapida" in last_outbound_norm:
            return False
        _SHIPPING_CONTEXT_TOKENS = {"envio", "cotizar", "cotice", "costo", "flete", "despacho", "domicilio", "delivery"}
        last_tokens = _tokenize_words(last_outbound_norm)
        # El último outbound debe tener contexto de envío Y no ser una solicitud de datos personales
        if (last_tokens & _SHIPPING_CONTEXT_TOKENS) and not any(m in last_outbound_norm for m in personal_data_markers):
            logger.info(
                "[SHIPPING_QUOTE] Followup afirmativo a ofrecimiento de envío | query=%s",
                query_text[:60],
            )
            return True

    # Fallback: query corto con city hint + contexto de envío activo en el ÚLTIMO outbound.
    # Cubre respuestas tipo "A Valledupar" cuando el LLM preguntó con frase no incluida en markers.
    if has_city_hint and len(tokens) <= 4 and last_outbound:
        last_outbound_norm = _normalize_text(str(last_outbound.get("content") or ""))
        # Si el bot ya mostró tarifas concretas, NO interceptamos como followup de envío
        if "economica" in last_outbound_norm or "rapida" in last_outbound_norm:
            return False
        _SHIPPING_CONTEXT_TOKENS = {"envio", "cotizar", "cotice", "costo", "flete", "despacho", "domicilio", "delivery"}
        last_tokens = _tokenize_words(last_outbound_norm)
        if last_tokens & _SHIPPING_CONTEXT_TOKENS:
            logger.info(
                "[SHIPPING_QUOTE] Followup por contexto activo de envío | query=%s",
                query_text[:60],
            )
            return True

    return False


def _resolve_destination_from_conversation(
    query_text: str,
    recent_messages: list[dict],
) -> tuple[Optional[dict], Optional[str]]:
    # 1) Prioridad al mensaje actual del cliente.
    destination, ambiguous_city = _resolve_destination_from_query(query_text)
    if destination or ambiguous_city:
        return destination, ambiguous_city

    # 2) Fallback a mensajes inbound recientes (contexto conversacional real).
    inbound_texts = [
        str(msg.get("content") or "").strip()
        for msg in recent_messages
        if str(msg.get("direction") or "").strip().lower() == "inbound"
    ]
    for text in inbound_texts:
        destination, ambiguous_city = _resolve_destination_from_query(text)
        if destination:
            return destination, None
        if ambiguous_city:
            return None, ambiguous_city

    # 3) Si el bot mencionó una ciudad en su último outbound (ej: "¿cotice a Bogotá?")
    # y el usuario respondió afirmativamente, inferir la ciudad desde el outbound.
    outbound_texts = [
        str(msg.get("content") or "").strip()
        for msg in recent_messages
        if str(msg.get("direction") or "").strip().lower() == "outbound"
    ]
    for text in outbound_texts[:2]:
        destination, ambiguous_city = _resolve_destination_from_query(text)
        if destination:
            return destination, None
        if ambiguous_city:
            return None, ambiguous_city

    # 4) Último intento: combinar señales de ubicación repartidas en varios mensajes.
    if inbound_texts:
        merged_text = " / ".join(inbound_texts[:3] + [query_text])
        destination, ambiguous_city = _resolve_destination_from_query(merged_text)
        if destination or ambiguous_city:
            return destination, ambiguous_city

    return None, None


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
    attrs = variation.get("attributes")
    if isinstance(attrs, dict) and attrs:
        parts = []
        for key in sorted(attrs.keys()):
            value = attrs.get(key)
            if value is None:
                continue
            parts.append(f"{key}: {value}")
        if parts:
            return ", ".join(parts)
    sku = str(variation.get("sku") or "").strip()
    return sku or "Estándar"


def _get_tenant_products_for_shipping_quote(supabase: Client, tenant_id: str) -> list[dict]:
    result = (
        supabase.table("products")
        .select(
            "title, product_variations("
            "sku, attributes, stock_quantity, weight_kg, length_cm, width_cm, height_cm)"
        )
        .eq("tenant_id", tenant_id)
        .eq("status", "active")
        .limit(120)
        .execute()
    )
    return result.data or []


def _score_product_against_text(product: dict, text: str) -> int:
    title = str(product.get("title") or "").strip()
    if not title:
        return 0

    normalized_title = _normalize_text(title)
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return 0

    title_tokens = _product_title_tokens(title)
    text_tokens = _tokenize_words(normalized_text)
    token_overlap = len(title_tokens & text_tokens)

    if normalized_title and normalized_title in normalized_text:
        # Match exacto de título tiene prioridad fuerte.
        return 100 + token_overlap
    if token_overlap <= 0:
        return 0
    return token_overlap * 10


def _resolve_product_for_quote(
    products: list[dict],
    query_text: str,
    recent_messages: list[dict],
) -> tuple[Optional[dict], list[str]]:
    if not products:
        return None, []

    # Si el catálogo activo tiene un único producto, usamos ese producto.
    if len(products) == 1:
        return products[0], []

    # 1) Buscar coincidencia explícita en query actual.
    explicit_matches: list[dict] = []
    normalized_query = _normalize_text(query_text)
    query_tokens = _tokenize_words(normalized_query)
    for product in products:
        title = str(product.get("title") or "").strip()
        if not title:
            continue
        normalized_title = _normalize_text(title)
        title_tokens = _product_title_tokens(title)
        if normalized_title and normalized_title in normalized_query:
            explicit_matches.append(product)
            continue
        # Evitar empates por artículos genéricos: requerimos >=2 tokens de título.
        if len(title_tokens & query_tokens) >= 2:
            explicit_matches.append(product)

    if len(explicit_matches) == 1:
        return explicit_matches[0], []
    if len(explicit_matches) > 1:
        return None, [str(p.get("title") or "").strip() for p in explicit_matches[:3]]

    # 2) Resolver por contexto conversacional reciente con score.
    message_window = [query_text]
    message_window.extend(
        [
            str(msg.get("content") or "")
            for msg in recent_messages
            if str(msg.get("content") or "").strip()
        ]
    )

    ranked: list[tuple[int, dict]] = []
    for product in products:
        best_score = 0
        for index, text in enumerate(message_window[:8]):
            base_score = _score_product_against_text(product, text)
            if base_score <= 0:
                continue
            # Bonus de recencia: mensajes más recientes pesan más.
            recency_bonus = max(1, 8 - index)
            best_score = max(best_score, base_score + recency_bonus)
        if best_score > 0:
            ranked.append((best_score, product))

    if not ranked:
        return None, []

    ranked.sort(key=lambda row: row[0], reverse=True)
    if len(ranked) == 1:
        return ranked[0][1], []

    top_score, top_product = ranked[0]
    second_score, second_product = ranked[1]
    # Ambigüedad controlada: no adivinar producto si la diferencia es baja.
    if second_score >= max(12, int(top_score * 0.88)):
        return None, [
            str(top_product.get("title") or "").strip(),
            str(second_product.get("title") or "").strip(),
        ]

    return top_product, []


def _select_best_variation_for_query(product: dict, query_text: str, recent_messages: list[dict]) -> Optional[dict]:
    variations = product.get("product_variations") or []
    if not variations:
        return None

    message_window = [query_text]
    message_window.extend(
        [
            str(msg.get("content") or "")
            for msg in recent_messages
            if str(msg.get("content") or "").strip()
        ]
    )

    scored: list[tuple[int, int, dict]] = []
    for variation in variations:
        searchable_parts = [
            str(variation.get("sku") or ""),
            _variation_label(variation),
        ]
        attrs = variation.get("attributes")
        if isinstance(attrs, dict):
            searchable_parts.extend([str(k) for k in attrs.keys()])
            searchable_parts.extend([str(v) for v in attrs.values()])
            
        variation_text = " ".join(searchable_parts).lower()
        if not variation_text.strip():
            continue
            
        variation_tokens = _tokenize_words(variation_text)
        
        best_score = 0
        for index, text in enumerate(message_window[:8]):
            norm_text = _normalize_text(text)
            text_tokens = _tokenize_words(norm_text)
            overlap = len(variation_tokens & text_tokens)
            
            # Si hay overlap exacto parcial o si la metadata literal aparece en el texto
            if overlap > 0 or any(part in norm_text for part in searchable_parts if len(part) > 3):
                recency_bonus = max(1, 8 - index)
                score = (overlap * 10) + recency_bonus
                best_score = max(best_score, score)

        stock = _safe_int(variation.get("stock_quantity")) or 0
        scored.append((best_score, stock, variation))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return scored[0][2] if scored else None


def _scale_dimension(base_value: float, quantity: int) -> float:
    if quantity <= 1:
        return base_value
    scale = quantity ** (1.0 / 3.0)
    return round(base_value * scale, 2)


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


def _estimate_package_from_inventory(
    supabase: Client,
    tenant_id: str,
    query_text: str,
    recent_messages: list[dict],
) -> PackageEstimateDecision:
    # Prioridad 1: peso explícito del cliente en texto.
    explicit_weight = _extract_weight_kg(query_text)
    quantity = _extract_requested_quantity(query_text)

    # T2: si el query actual no tiene cantidad, buscarla en historial inbound reciente
    if quantity == 1:
        for msg in recent_messages:
            if str(msg.get("direction") or "").strip().lower() != "inbound":
                continue
            content_str = str(msg.get("content") or "")
            if re.search(r"calle|cra|carrera|sur|norte", _normalize_text(content_str)):
                continue
            q = _extract_requested_quantity(content_str)
            if q > 1:
                quantity = q
                logger.info(
                    "[SHIPPING_QUOTE] Cantidad %d inferida del historial conversacional", quantity
                )
                break

    try:
        products = _get_tenant_products_for_shipping_quote(supabase, tenant_id)
    except Exception as exc:
        logger.warning("No se pudo cargar catálogo para estimar paquete shipping tenant=%s: %s", tenant_id, exc)
        products = []

    product, ambiguous_titles = _resolve_product_for_quote(
        products=products,
        query_text=query_text,
        recent_messages=recent_messages,
    )
    if ambiguous_titles:
        return PackageEstimateDecision(package=None, ambiguous_product_titles=ambiguous_titles)

    if not product:
        fallback_weight = explicit_weight if explicit_weight is not None else DEFAULT_WEIGHT_KG
        return PackageEstimateDecision(
            package=PackageEstimate(
                weight_kg=max(fallback_weight, 0.05),
                length_cm=DEFAULT_LENGTH_CM,
                width_cm=DEFAULT_WIDTH_CM,
                height_cm=DEFAULT_HEIGHT_CM,
                quantity=max(quantity, 1),
                source="default",
            )
        )

    # Usar historial reciente para encontrar tallas, colores o atributos omitidos
    best_variation = _select_best_variation_for_query(product, query_text, recent_messages) or {}
    var_weight = _safe_float(best_variation.get("weight_kg"))
    var_length = _safe_float(best_variation.get("length_cm"))
    var_width = _safe_float(best_variation.get("width_cm"))
    var_height = _safe_float(best_variation.get("height_cm"))

    per_unit_weight = explicit_weight if explicit_weight is not None else (
        var_weight if var_weight and var_weight > 0 else DEFAULT_WEIGHT_KG
    )
    total_weight = max(per_unit_weight, 0.05) * max(quantity, 1)

    base_length = var_length if var_length and var_length > 0 else DEFAULT_LENGTH_CM
    base_width = var_width if var_width and var_width > 0 else DEFAULT_WIDTH_CM
    base_height = var_height if var_height and var_height > 0 else DEFAULT_HEIGHT_CM

    # Extraer TODAS las variantes mencionadas en historial para este producto.
    # Si el cliente pidió 1 Roja + 1 Azul, mostrar "Rojo y Azul" en vez de solo "Rojo".
    variant_label_final = _variation_label(best_variation) if best_variation else None
    if quantity > 1 and (product.get("product_variations") or []):
        all_variations = product.get("product_variations") or []
        all_labels: list[str] = []
        combined_hist = " ".join(
            str(m.get("content") or "")
            for m in recent_messages
            if str(m.get("direction") or "").lower() == "inbound"
        )
        norm_hist = _normalize_text(combined_hist)
        hist_tokens = _tokenize_words(norm_hist)
        for v in all_variations:
            vl = _variation_label(v)
            if vl and _tokenize_words(_normalize_text(vl)) & hist_tokens:
                all_labels.append(vl)
        unique_labels = list(dict.fromkeys(all_labels))  # orden preservado, sin duplicados
        if len(unique_labels) >= 2:
            variant_label_final = " y ".join(unique_labels[:3])  # máx 3 para no saturar
        elif len(unique_labels) == 1:
            variant_label_final = unique_labels[0]

    return PackageEstimateDecision(
        package=PackageEstimate(
            weight_kg=round(max(total_weight, 0.05), 3),
            length_cm=_scale_dimension(base_length, max(quantity, 1)),
            width_cm=_scale_dimension(base_width, max(quantity, 1)),
            height_cm=_scale_dimension(base_height, max(quantity, 1)),
            quantity=max(quantity, 1),
            product_title=_clean_product_title(str(product.get("title") or "").strip()) or None,
            variant_label=variant_label_final,
            source="inventory",
        )
    )


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


def _build_api_auth_token(tenant_id: str) -> Optional[str]:
    if not SUPABASE_JWT_SECRET:
        return None
    now = datetime.now(timezone.utc)
    payload = {
        "aud": "authenticated",
        "sub": "00000000-0000-0000-0000-000000000000",
        "role": "authenticated",
        "email": "orchestrator@system.local",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "app_metadata": {
            "tenant_id": tenant_id,
            "role": "owner",
        },
        "user_metadata": {},
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def _coerce_origin(raw: Optional[dict]) -> Optional[dict]:
    source = dict(raw or {})

    if not source:
        return None

    city = str(source.get("city") or "").strip()
    state = str(source.get("state") or "").strip()
    country = _normalize_country_code(source.get("country"), default="CO")
    dane_code = _sanitize_dane_code(source.get("dane_code") or source.get("postal_code"))
    if not dane_code or not city or not state:
        return None

    out = {
        "city": city,
        "state": state,
        "country": country,
        "postalCode": dane_code,
        "dane_code": dane_code,
    }
    # Rev. 68 — district (barrio) opcional. Algunos carriers (Coordinadora,
    # Servientrega) lo usan para optimizar zona de despacho.
    neighborhood = str(source.get("neighborhood") or "").strip()
    if neighborhood:
        out["district"] = neighborhood
    return out


def _coerce_destination(raw: Optional[dict]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    city = str(raw.get("city") or "").strip()
    state = str(raw.get("state") or "").strip()
    country = _normalize_country_code(raw.get("country"), default="CO")
    dane_code = _sanitize_dane_code(raw.get("dane_code") or raw.get("postal_code"))
    if not dane_code:
        return None

    out = {
        "city": city,
        "state": state,
        "country": country,
        "postalCode": dane_code,
        "dane_code": dane_code,
    }
    # Rev. 68 — district (barrio) opcional desde contact.address.neighborhood.
    neighborhood = str(raw.get("neighborhood") or "").strip()
    if neighborhood:
        out["district"] = neighborhood
    return out


def _build_quote_payload(origin: dict, destination: dict, package: PackageEstimate) -> dict:
    return {
        "origin": origin,
        "destination": destination,
        "parcels": [
            {
                "weight": max(package.weight_kg, 0.05),
                "length": max(package.length_cm, 1.0),
                "width": max(package.width_cm, 1.0),
                "height": max(package.height_cm, 1.0),
                "amount": max(package.quantity, 1),
                "content": package.product_title or "Mercancía general",
                "insuranceAmount": 0,
            }
        ],
    }


def _get_tenant_shipping_origin(supabase: Client, tenant_id: str) -> Optional[dict]:
    res = (
        supabase.table("tenants")
        .select("shipping_origin")
        .eq("id", tenant_id)
        .single()
        .execute()
    )
    return (res.data or {}).get("shipping_origin")


def _get_conversation_customer_phone(supabase: Client, conversation_id: str) -> Optional[str]:
    res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not res.data:
        return None
    return str(res.data.get("customer_phone") or "").strip() or None


def _get_contact_address(
    supabase: Client,
    tenant_id: str,
    customer_phone: Optional[str],
) -> Optional[dict]:
    if not customer_phone:
        return None

    # T3: WhatsApp envía sin '+', contactos pueden estar registrados con o sin '+'
    # Intentamos ambos formatos para no perder el match.
    phone_norm = _normalize_phone(customer_phone)
    phone_plus = f"+{phone_norm}"

    res = (
        supabase.table("contacts")
        .select("address")
        .eq("tenant_id", tenant_id)
        .or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus}")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    address = rows[0].get("address")
    return address if isinstance(address, dict) else None


async def _request_shipping_quote(tenant_id: str, payload: dict) -> tuple[int, dict]:
    token = _build_api_auth_token(tenant_id)
    if not token:
        return 500, {"detail": "SUPABASE_JWT_SECRET no configurado en orquestador."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"inbox-quote-{uuid.uuid4()}",
    }

    timeout = httpx.Timeout(SHIPPING_REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{API_URL}/api/v1/shipping/quote", json=payload, headers=headers)
        body = resp.json() if resp.content else {}
        if not isinstance(body, dict):
            body = {"detail": "Respuesta inválida del servicio de shipping."}
        return resp.status_code, body


def _build_quote_failure_response(detail: str, status_code: int) -> tuple[str, bool]:
    normalized = _normalize_text(detail)

    if "envia no esta conectado" in normalized or "api token de envia no encontrado" in normalized:
        return (
            "En este momento no tengo habilitada la cotización automática de envío. Te paso con un asesor experto.",
            True,
        )

    if "codigo dane valido" in normalized:
        return (
            "Para cotizar envío necesito ciudad y departamento de entrega para ubicar el destino correctamente.",
            False,
        )

    if status_code in {400, 422}:
        return (
            "No pude validar la información para cotizar el envío. Confírmame ciudad y departamento.",
            False,
        )

    return (
        "No pude cotizar el envío en este momento. Intentemos de nuevo en unos minutos.",
        False,
    )


async def handle_shipping_quote_if_applicable(
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
    query_text: str,
) -> ShippingQuoteResult:
    recent_messages = _get_recent_conversation_messages(supabase, conversation_id)
    if not _is_shipping_followup_query(query_text, recent_messages):
        return ShippingQuoteResult(handled=False)

    try:
        origin_cfg = _get_tenant_shipping_origin(supabase, tenant_id)
        origin = _coerce_origin(origin_cfg)
        if not origin:
            return ShippingQuoteResult(
                handled=True,
                response_text=(
                    "Para cotizar envío necesito la Dirección de origen del tenant. "
                    "Configúrala en Ajustes > Dirección de envío."
                ),
                requires_human=True,
            )

        phone = _get_conversation_customer_phone(supabase, conversation_id)
        contact_address = _get_contact_address(supabase, tenant_id, phone)
        destination = _coerce_destination(contact_address)
        if not destination:
            destination, ambiguous_city = _resolve_destination_from_conversation(
                query_text=query_text,
                recent_messages=recent_messages,
            )
        if not destination:
            if ambiguous_city:
                return ShippingQuoteResult(
                    handled=True,
                    response_text=(
                        f"Para cotizar envío a {ambiguous_city}, indícame también el departamento."
                    ),
                )
            return ShippingQuoteResult(
                handled=True,
                response_text=(
                    "Para cotizar envío necesito tu ciudad de entrega (por ejemplo: Medellín)."
                ),
            )

        package_decision = _estimate_package_from_inventory(
            supabase=supabase,
            tenant_id=tenant_id,
            query_text=query_text,
            recent_messages=recent_messages,
        )
        if package_decision.ambiguous_product_titles:
            # Contar cuántas veces ya pedimos confirmación del producto (stall detection)
            stall_count = sum(
                1 for msg in recent_messages
                if str(msg.get("direction") or "") == "outbound"
                and any(
                    marker in _normalize_text(str(msg.get("content") or ""))
                    for marker in (
                        "para cotizar envio con precision",
                        "para cotizar envio necesito confirmar",
                    )
                )
            )
            if stall_count >= 2:
                logger.info(
                    "[SHIPPING_QUOTE] Stall detectado (%d rondas) para tenant=%s — escalando a un experto",
                    stall_count, tenant_id,
                )
                return ShippingQuoteResult(
                    handled=True,
                    response_text=(
                        "No pude identificar el producto exacto para cotizar el envío. "
                        "Te paso con un asesor para ayudarte mejor."
                    ),
                    requires_human=True,
                )
            return ShippingQuoteResult(
                handled=True,
                response_text=_build_product_disambiguation_text(
                    package_decision.ambiguous_product_titles
                ),
            )

        package = package_decision.package or PackageEstimate(
            weight_kg=DEFAULT_WEIGHT_KG,
            length_cm=DEFAULT_LENGTH_CM,
            width_cm=DEFAULT_WIDTH_CM,
            height_cm=DEFAULT_HEIGHT_CM,
            quantity=1,
            source="default",
        )

        payload = _build_quote_payload(origin, destination, package)
        status_code, body = await _request_shipping_quote(tenant_id, payload)

        if status_code >= 400:
            detail = str(body.get("detail") or "No pude cotizar el envio en este momento.")
            response_text, requires_human = _build_quote_failure_response(detail, status_code)
            logger.warning(
                "[SHIPPING_QUOTE] Error cotizando tenant=%s status=%s detail=%s",
                tenant_id,
                status_code,
                detail,
            )
            return ShippingQuoteResult(
                handled=True,
                response_text=response_text,
                requires_human=requires_human,
            )

        highlights = body.get("highlights") if isinstance(body, dict) else {}
        message = _build_quote_response_text(origin, destination, highlights, package)
        if not message:
            return ShippingQuoteResult(
                handled=True,
                response_text="No llegaron tarifas disponibles en este momento. Intentemos nuevamente en unos minutos.",
                requires_human=True,
            )
        return ShippingQuoteResult(handled=True, response_text=message)
    except Exception as exc:
        logger.error("Error en shipping_quote_tool tenant=%s: %s", tenant_id, exc, exc_info=True)
        return ShippingQuoteResult(
            handled=True,
            response_text="No pude cotizar el envio ahora mismo. Te apoyo con un asesor experto.",
            requires_human=True,
        )
