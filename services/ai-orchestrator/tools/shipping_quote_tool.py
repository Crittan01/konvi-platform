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
# PyJWT removed in A0.2c — service-to-service auth via INTERNAL_SERVICE_SECRET header
from supabase import Client

logger = logging.getLogger("orchestrator.tools.shipping_quote")

API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
# A0.2c 2026-05-31 — service-to-service auth header-based (reemplaza JWT HS256).
INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

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
    # Sem 7 F2 cierre 2026-05-20 — Bug founder UAT (conv 56ff85d8):
    # El bot emite "Para qué ciudad es el envío?" tras "Cotizar" del cliente.
    # Cuando el cliente respondía solo "Bogota", el detector NO matcheaba
    # ningún marker → tool retornaba False → LLM tomaba control → respondía
    # texto genérico de KB sobre tiempos de entrega y saltaba a flow PII
    # SIN cotizar realmente. Faltaba esta familia de markers canónicos.
    "para que ciudad es el envio",       # "Para qué ciudad es el envío?"
    "para que ciudad es",                 # variante corta
    "a que ciudad va",                    # "¿A qué ciudad va tu pedido?"
    "a que ciudad enviamos",              # "¿A qué ciudad enviamos?"
    "cual es la ciudad",                  # "¿Cuál es la ciudad de entrega?"
    "ciudad de entrega",                  # general
    "me dices la ciudad",                 # "me dices la ciudad de entrega"
    "me dices a que ciudad",              # variante
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

    # Rev. 76 — guard adicional: NO interceptar como followup de envío si el
    # último outbound es el resumen final con CTA de pago. Antes el detector
    # malinterpretaba "Ok, gracias" tras el resumen como "sí cotiza" porque
    # el resumen contiene la palabra "envío" + un costo.
    # Detectado en UAT E2E real (conv c2043f98 turn 12).
    #
    # Sem 7 F2 cierre 2026-05-20 — Bug founder UAT (conv 56ff85d8):
    # ANTES "subtotal:" estaba en summary_markers. Eso causaba falso
    # positivo en el mini-resumen pre-cotización (T10 del log: "Productos
    # en tu carrito... Subtotal: $56.000 ... Para qué ciudad es el envío?")
    # — el detector lo confundía con el resumen FINAL → retornaba False →
    # tool no se invocaba → bot saltaba a flow PII sin cotizar.
    # FIX: "subtotal:" es genérico (aparece tanto en mini-resumen pre-cot
    # como en resumen final). Los otros markers son ESPECÍFICOS al resumen
    # final (header "Resumen de tu pedido", CTA "link de pago", "datos
    # correctos") y bastan para distinguir.
    summary_markers = [
        "resumen de tu pedido",
        "datos estan correctos",
        "datos están correctos",
        "generar tu link de pago",
        "para generar tu link",
        "tu link de pago",
    ]
    if any(m in outbound_text for m in summary_markers):
        return False

    has_separator = "/" in query_text or "," in query_text
    # Sem 7 F2 cierre 2026-05-20 — prefijos en vez de tokens exactos para
    # cubrir variantes verbales del español: "envio"/"envia"/"enviamos"/
    # "enviar", "cotizar"/"cotizamos"/"cotice", "entrega"/"entregar"/
    # "entregamos", etc. El guard previo `personal_data_markers` ya
    # bloquea outbounds de captura PII ("dirección de entrega..."), por
    # lo que estos prefijos aquí solo matchean cotización legítima.
    _shipping_context_prefixes = (
        "envi",       # envio, envía, enviamos, enviar, envío
        "cotiz",      # cotizar, cotizamos, cotizo
        "cotice",     # subjuntivo
        "costo",      # costos también
        "flete",
        "despach",    # despacho, despachar, despachamos
        "domicili",
        "deliver",    # delivery, deliveries
        "entreg",     # entrega, entregar, entregamos
    )
    marker_matched = any(marker in outbound_text for marker in _SHIPPING_FOLLOWUP_PROMPT_MARKERS)
    has_shipping_context = any(
        any(tok.startswith(p) for p in _shipping_context_prefixes)
        for tok in _tokenize_words(outbound_text)
    )
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


# Estructura declarativa: cada tupla = (forma canónica, alias). El dict
# se construye una sola vez al import. Más legible que repetir `"X": "X"`.
_UNIT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Peso
    ("g",  ("g", "gr", "gms", "gramo", "gramos")),
    ("kg", ("kg", "kilo", "kilos", "kilogramo", "kilogramos")),
    ("mg", ("mg", "miligramo", "miligramos")),
    # Volumen
    ("ml", ("ml", "mls", "mililitro", "mililitros", "cc")),
    ("l",  ("l", "lt", "lts", "litro", "litros")),
    ("cl", ("cl", "centilitro", "centilitros")),
    # Imperial
    ("oz", ("oz", "onza", "onzas")),
    ("lb", ("lb", "lbs", "libra", "libras")),
    # Largo
    ("cm", ("cm", "cms", "centimetro", "centimetros", "centímetro", "centímetros")),
    ("m",  ("m", "metro", "metros")),
    ("mm", ("mm", "milimetro", "milimetros", "milímetro", "milímetros")),
    ("in", ("in", "pulgada", "pulgadas")),
    # Cantidad / empaque
    ("u",    ("u", "und", "uds", "unidad", "unidades")),
    ("pack", ("pack", "packs")),
)

_UNIT_CANONICAL_MAP: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _UNIT_GROUPS
    for alias in aliases
}


def _canonicalize_unit_value(text: str) -> str:
    """Rev. 92.c — Normaliza valores de variante con unidad a forma canónica.

    Ejemplos:
      • "30 mililitros" → "30ml"
      • "60 gramos"     → "60g"
      • "1 kilo"        → "1kg"
      • "12 oz"         → "12oz"
      • "30ml"          → "30ml"   (idempotente)
      • "Talla M"       → "Talla M" (sin número-unidad reconocible, no toca)

    Caso multi-tenant: cualquier tenant puede escribir la unidad como
    le parezca; el cliente igual la dice como quiera. El bot muestra y
    matchea contra forma canónica única.
    """
    if not text or not isinstance(text, str):
        return text
    raw = text.strip()
    # Patrón: número (entero/decimal) seguido de unidad (con/sin espacio).
    import re as _re
    match = _re.match(
        r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-zÁÉÍÓÚáéíóú]+)\.?\s*$",
        raw,
    )
    if not match:
        return raw
    qty, unit = match.group(1), match.group(2).lower()
    canonical_unit = _UNIT_CANONICAL_MAP.get(unit)
    if canonical_unit is None:
        return raw  # Unidad desconocida — preservar literal.
    # Normalizar separador decimal a "." y compactar.
    qty_norm = qty.replace(",", ".")
    return f"{qty_norm}{canonical_unit}"


def _variation_label(variation: dict) -> str:
    """Etiqueta legible de una variante para captions / cotizaciones.

    Rev. 92.c — (1) Si hay UN solo atributo, devolver solo el valor
    canonicalizado (evita "Volumen: 30ml" cuando "30ml" es suficiente).
    (2) Normaliza unidades ("30 mililitros" → "30ml", "60 gramos" → "60g").
    (3) Si hay múltiples atributos, preserva "Key: Value, Key: Value".
    """
    attrs = variation.get("attributes")
    if isinstance(attrs, dict) and attrs:
        non_null = {k: v for k, v in attrs.items() if v not in (None, "")}
        if len(non_null) == 1:
            raw_value = str(next(iter(non_null.values()))).strip()
            return _canonicalize_unit_value(raw_value)
        if len(non_null) > 1:
            return ", ".join(
                f"{k}: {_canonicalize_unit_value(str(non_null[k]))}"
                for k in sorted(non_null.keys())
            )
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
    # Separar match COMPLETO del título (norm_title in query) de match parcial
    # por tokens. Si hay un único match completo, ese gana — incluso si otros
    # productos comparten tokens genéricos (ej "Aceite Esencial de Lavanda"
    # gana sobre los otros esenciales que comparten "aceite"+"esencial").
    full_matches: list[dict] = []
    token_matches: list[dict] = []
    normalized_query = _normalize_text(query_text)
    query_tokens = _tokenize_words(normalized_query)
    for product in products:
        title = str(product.get("title") or "").strip()
        if not title:
            continue
        normalized_title = _normalize_text(title)
        title_tokens = _product_title_tokens(title)
        if normalized_title and normalized_title in normalized_query:
            full_matches.append(product)
        elif len(title_tokens & query_tokens) >= 2:
            token_matches.append(product)

    if len(full_matches) == 1:
        return full_matches[0], []
    if len(full_matches) > 1:
        # Match completo de varios títulos en la misma query — caso raro.
        return None, [str(p.get("title") or "").strip() for p in full_matches[:3]]

    if len(token_matches) == 1:
        return token_matches[0], []
    if len(token_matches) > 1:
        return None, [str(p.get("title") or "").strip() for p in token_matches[:3]]

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


def _resolve_multiple_products_with_quantities(
    products: list[dict],
    query_text: str,
    recent_messages: list[dict],
) -> list[tuple[dict, int]]:
    """Detecta múltiples productos mencionados explícitamente en query/history
    con sus cantidades. Devuelve [] si no hay >= 2 productos distintos —
    deja que el single-product resolver tome el control.

    Útil para que la cotización Envia sume peso/dimensiones de TODO el carrito
    cuando el cliente pide ej. "2 aceites de coco y 1 sérum de vitamina C".
    """
    if not products or len(products) < 2:
        return []
    full_text = (query_text or "")
    for msg in (recent_messages or [])[:6]:
        if str(msg.get("direction") or "").lower() == "inbound":
            full_text += "\n" + str(msg.get("content") or "")
    norm_text = _normalize_text(full_text)
    norm_text_tokens = _tokenize_words(norm_text)

    matched: list[tuple[dict, int, bool]] = []  # (product, qty, qty_es_explicito)
    seen_titles: set[str] = set()
    for product in products:
        title = str(product.get("title") or "").strip()
        if not title:
            continue
        norm_title = _normalize_text(title)
        if norm_title in seen_titles:
            continue
        title_tokens = _product_title_tokens(title)
        if norm_title and norm_title in norm_text:
            pass
        elif title_tokens and len(title_tokens & norm_text_tokens) >= 2:
            pass
        else:
            continue
        seen_titles.add(norm_title)
        explicit_qty = _extract_quantity_near_phrase(norm_text, list(title_tokens))
        matched.append((product, explicit_qty if explicit_qty > 0 else 1, explicit_qty > 0))

    # Solo activar multi cuando hay 2+ productos Y al menos uno tiene cantidad
    # explícita en el texto (ej "2 aceites... 1 sérum"). Si solo aparecen nombres
    # sin números, dejar que el single-resolver pida desambiguación.
    if len(matched) < 2 or not any(is_explicit for _, _, is_explicit in matched):
        return []
    return [(p, q) for p, q, _ in matched]


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


def _estimate_package_from_cart_if_available(
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
) -> Optional["PackageEstimateDecision"]:
    """Rev. 81 (A.3 + B) — si el cart en DB tiene items, construye el
    PackageEstimate directamente desde sus dims (saltando disambiguation).

    Devuelve None si no hay cart con items — el caller cae al resolver
    de inventario tradicional.
    """
    try:
        from tools.cart_tool import get_cart_with_items, compute_shipping_inputs
    except Exception as exc:
        logger.warning("[SHIPPING_QUOTE] cart_tool no disponible: %s", exc)
        return None

    try:
        cart = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("[SHIPPING_QUOTE] get_cart_with_items falló: %s", exc)
        return None

    items = (cart or {}).get("items") or []
    if not items:
        return None

    inputs = compute_shipping_inputs(cart)
    weight_kg = max(float(inputs.get("billable_weight_kg") or 0.0), 0.05)
    dims = inputs.get("package_dims") or {}
    L = float(dims.get("length_cm") or 0.0) or DEFAULT_LENGTH_CM
    W = float(dims.get("width_cm") or 0.0) or DEFAULT_WIDTH_CM
    H = float(dims.get("height_cm") or 0.0) or DEFAULT_HEIGHT_CM
    total_qty = sum(int(it.get("quantity") or 1) for it in items)

    summaries: list[str] = []
    for it in items[:3]:
        p = it.get("product") or {}
        v = it.get("variation") or {}
        title = _clean_product_title(str(p.get("title") or p.get("name") or "Producto"))
        label = v.get("label") or v.get("presentation") or ""
        qty = int(it.get("quantity") or 1)
        qstr = f"{qty}x" if qty > 1 else "1x"
        summaries.append(f"{qstr} {title}" + (f" ({label})" if label else ""))
    title_str = " + ".join(summaries) + (
        f" + {len(items) - 3} más" if len(items) > 3 else ""
    )

    logger.info(
        "[SHIPPING_QUOTE] cart-as-SoT: %d items, billable=%skg, dims=%sx%sx%s",
        total_qty, weight_kg, L, W, H,
    )
    return PackageEstimateDecision(
        package=PackageEstimate(
            weight_kg=round(weight_kg, 3),
            length_cm=L,
            width_cm=W,
            height_cm=H,
            quantity=total_qty,
            product_title=title_str,
            variant_label=None,
            source="cart_db",
        )
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

    # Multi-producto: si el cliente pidió 2+ productos, sumar peso y dimensiones.
    # Bug 18 — antes solo se cotizaba un producto y el cliente terminaba pagando
    # un envío sub-dimensionado.
    multi_items = _resolve_multiple_products_with_quantities(products, query_text, recent_messages)
    if len(multi_items) >= 2:
        total_weight = 0.0
        max_length = 0.0
        max_width = 0.0
        max_height = 0.0
        total_quantity = 0
        product_summaries: list[str] = []
        for prod, qty in multi_items:
            best_var = _select_best_variation_for_query(prod, query_text, recent_messages) or {}
            w = _safe_float(best_var.get("weight_kg")) or DEFAULT_WEIGHT_KG
            l_cm = _safe_float(best_var.get("length_cm")) or DEFAULT_LENGTH_CM
            wd_cm = _safe_float(best_var.get("width_cm")) or DEFAULT_WIDTH_CM
            h_cm = _safe_float(best_var.get("height_cm")) or DEFAULT_HEIGHT_CM
            total_weight += max(w, 0.05) * max(qty, 1)
            max_length = max(max_length, l_cm)
            max_width = max(max_width, wd_cm)
            max_height = max(max_height, h_cm)
            total_quantity += max(qty, 1)
            title = _clean_product_title(str(prod.get("title") or ""))
            label = _variation_label(best_var) if best_var else None
            qstr = f"{qty}x" if qty > 1 else "1x"
            if label:
                product_summaries.append(f"{qstr} {title} ({label})")
            else:
                product_summaries.append(f"{qstr} {title}")
        logger.info(
            "[SHIPPING_QUOTE] Multi-producto detectado: %s items totales (%d productos distintos)",
            total_quantity, len(multi_items),
        )
        return PackageEstimateDecision(
            package=PackageEstimate(
                weight_kg=round(max(total_weight, 0.05), 3),
                length_cm=_scale_dimension(max_length, total_quantity),
                width_cm=_scale_dimension(max_width, total_quantity),
                height_cm=_scale_dimension(max_height, total_quantity),
                quantity=total_quantity,
                product_title=" + ".join(product_summaries[:3]) + (
                    f" + {len(product_summaries)-3} más" if len(product_summaries) > 3 else ""
                ),
                variant_label=None,
                source="multi",
            )
        )

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


def _build_internal_headers(tenant_id: str) -> Optional[dict]:
    """Headers para auth service-to-service (A0.2c). Retorna None si secret falta."""
    if not INTERNAL_SERVICE_SECRET:
        return None
    return {
        "X-Internal-Service-Secret": INTERNAL_SERVICE_SECRET,
        "X-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
        "Idempotency-Key": f"inbox-quote-{uuid.uuid4()}",
    }


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


def _get_contact_shipping_phone(
    supabase: Client,
    tenant_id: str,
    customer_phone: Optional[str],
) -> Optional[str]:
    """Rev. 103 — devuelve `contacts.shipping_phone` si existe, sino
    fallback al `customer_phone` (WhatsApp). Útil para construir el
    `destination.phone` del shipment con el phone del receptor real.
    """
    if not customer_phone:
        return None
    phone_norm = _normalize_phone(customer_phone)
    phone_plus = f"+{phone_norm}"
    res = (
        supabase.table("contacts")
        .select("phone, shipping_phone")
        .eq("tenant_id", tenant_id)
        .or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus}")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return phone_plus  # fallback
    ship = (rows[0].get("shipping_phone") or "").strip()
    base = (rows[0].get("phone") or "").strip()
    return ship or base or phone_plus


async def _request_shipping_quote(tenant_id: str, payload: dict) -> tuple[int, dict]:
    """Llama a /api/v1/shipping/quote con resiliencia ante transients.

    Rev. 103 — Envia upstream ocasionalmente tarda > 25s. Reintento único
    antes de devolver 504 (mapea a respuesta soft, NO escala a humano).
    Solo errores reales (4xx, falta config) escalan.
    """
    headers = _build_internal_headers(tenant_id)
    if not headers:
        return 500, {"detail": "INTERNAL_SERVICE_SECRET no configurado en orquestador."}

    timeout = httpx.Timeout(SHIPPING_REQUEST_TIMEOUT_SECONDS)
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{API_URL}/api/v1/shipping/quote",
                    json=payload, headers=headers,
                )
                body = resp.json() if resp.content else {}
                if not isinstance(body, dict):
                    body = {"detail": "Respuesta inválida del servicio de shipping."}
                return resp.status_code, body
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "[SHIPPING_QUOTE] transient error attempt=%d tenant=%s err=%s",
                attempt + 1, tenant_id, exc,
            )
    return 504, {"detail": f"transient_timeout: {last_exc}"}


def _build_quote_failure_response(detail: str, status_code: int) -> tuple[str, bool]:
    normalized = _normalize_text(detail)

    if (
        "aveonline no esta conectado" in normalized
        or "aveonline no autenticado" in normalized
        or "provider shipping" in normalized
    ):
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

    # 504 = transient (timeout tras reintento). NO escalar a humano —
    # cliente reintenta sin perder contexto. Diferenciar de 5xx persistente.
    if status_code == 504:
        return (
            "El servicio de cotización está tardando más de lo esperado. "
            "¿Probamos de nuevo en unos segundos?",
            False,
        )

    return (
        "No pude cotizar el envío en este momento. Intentemos de nuevo en unos minutos.",
        False,
    )


def _persist_destination_city_to_cart(
    supabase: Client,
    *,
    tenant_id: str,
    conversation_id: str,
    destination: dict,
) -> None:
    """Plan A.0.1 / ADR-0011 §6.5 — persiste city al cart en cuanto se resuelve.

    Idempotente: si el cart ya tiene la misma city, no hace nada. Solo
    actualiza si la city es nueva o estaba vacía. NO toca carrier/service
    ni `requires_requote` (eso es responsabilidad de set_shipping_meta al
    confirmar carrier o de invalidate_shipping al modificar items).

    Esta persistencia temprana cierra la ventana donde `cart.shipping_meta.city`
    estaba vacío entre el momento en que el cliente declara la city y el
    momento en que se confirma carrier — ventana en la que una modificación
    de cart hubiera dejado a `requote_shipping_for_cart` sin city para
    construir el payload Envia.
    """
    new_city = (destination.get("city") or "").strip()
    if not new_city:
        return
    new_dane = (destination.get("dane_code") or destination.get("postalCode") or "")
    new_dane = str(new_dane).strip() or None

    res = (
        supabase.table("conversation_carts")
        .select("id, shipping_meta")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conversation_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not res.data:
        return
    cart_row = res.data[0]
    cart_id = cart_row["id"]
    meta = cart_row.get("shipping_meta") or {}
    if (meta.get("city") or "").strip() == new_city:
        return  # idempotente

    # Merge no destructivo: preserva carrier/service/rate_id/etc si existen.
    new_meta = dict(meta)
    new_meta["city"] = new_city
    if new_dane:
        new_meta["dane_code"] = new_dane

    supabase.table("conversation_carts").update({
        "shipping_meta": new_meta,
    }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    logger.info(
        "[SHIPPING_QUOTE] persistida city=%s al cart=%s (prev=%s)",
        new_city, cart_id[:8], meta.get("city") or "vacío",
    )


async def requote_shipping_for_cart(
    supabase: Client,
    *,
    tenant_id: str,
    conversation_id: str,
) -> Optional[dict]:
    """Recotización lazy de envío post-modificación del cart (ADR-0011 §6.5).

    Pensado para invocación silenciosa cuando `cart.requires_requote=true`,
    típicamente tras `cart_tool.add_item` / `remove_item` con orden previa
    invalidada. NO emite mensaje al cliente; el caller decide cómo informar.

    Flujo:
      1. Lee cart.shipping_meta para obtener city + carrier elegido previo.
      2. Calcula package (peso billable + dims) desde items actuales del cart.
      3. Llama Envia (`_request_shipping_quote`) con el payload nuevo.
      4. Intenta preservar la elección previa del cliente (si seleccionó
         "Económica" antes y todavía está disponible, devuelve esa rate).
         Fallback: cheapest.
      5. Retorna dict con {shipping_cents, carrier_name, service_level}
         para que el caller persista vía `cart_tool.set_shipping_meta` y
         actualice el `verified_ctx` antes de generar resumen+link.

    Retorna None si:
      • cart vacío o sin items
      • origin/destination no resolvibles
      • Envia rechaza la cotización (4xx) o transient (504)

    El caller debe degradar a comportamiento previo (reusar shipping del
    history) si retorna None — preferimos shipping stale a no tener
    resumen, pero loggeamos el evento para alertar.
    """
    try:
        from tools.cart_tool import get_cart_with_items
    except Exception as exc:  # pragma: no cover
        logger.warning("[REQUOTE_LAZY] cart_tool no disponible: %s", exc)
        return None

    try:
        cart = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("[REQUOTE_LAZY] get_cart falló conv=%s: %s",
                       conversation_id[:8], exc)
        return None

    if not cart or not (cart.get("items") or []):
        return None

    shipping_meta = cart.get("shipping_meta") or {}
    city_known = (shipping_meta.get("city") or "").strip()
    if not city_known:
        # Cart-as-SoT: city debe estar persistida desde la primera cotización
        # exitosa (handle_shipping_quote_if_applicable lo hace vía
        # _persist_destination_city_to_cart). Si no está, abortamos —
        # no caemos a heurísticas de history-parsing (Plan A.0.2).
        logger.warning(
            "[REQUOTE_LAZY] cart.shipping_meta.city vacío — abortando recotización "
            "(esperado: handle_shipping_quote_if_applicable persiste la city)"
        )
        return None

    # Resolver origen del tenant.
    try:
        origin_cfg = _get_tenant_shipping_origin(supabase, tenant_id)
        origin = _coerce_origin(origin_cfg)
    except Exception as exc:
        logger.warning("[REQUOTE_LAZY] origin lookup falló: %s", exc)
        return None
    if not origin:
        return None

    # Destino desde city del cart.shipping_meta (autoritario post-fix S14).
    destination, _ambiguous = _resolve_destination_from_conversation(
        query_text=f"envío a {city_known}",
        recent_messages=[],
    )
    if not destination:
        logger.warning(
            "[REQUOTE_LAZY] no pude resolver destination city=%s", city_known,
        )
        return None
    # Recipient phone si está en contact (best-effort)
    try:
        phone = _get_conversation_customer_phone(supabase, conversation_id)
        if phone:
            recipient_phone = _get_contact_shipping_phone(supabase, tenant_id, phone)
            if recipient_phone:
                destination["phone"] = recipient_phone
    except Exception:
        pass

    # Package desde cart actual (peso/dims actualizados).
    pkg_decision = _estimate_package_from_cart_if_available(
        supabase, tenant_id, conversation_id,
    )
    if pkg_decision is None or pkg_decision.package is None:
        logger.warning("[REQUOTE_LAZY] no pude estimar package desde cart")
        return None
    package = pkg_decision.package

    payload = _build_quote_payload(origin, destination, package)
    try:
        status_code, body = await _request_shipping_quote(tenant_id, payload)
    except Exception as exc:  # pragma: no cover (defensivo)
        logger.warning("[REQUOTE_LAZY] _request_shipping_quote excepción: %s", exc)
        return None

    if status_code >= 400:
        logger.warning(
            "[REQUOTE_LAZY] Envia status=%s body=%s",
            status_code, str(body)[:200],
        )
        return None

    highlights = body.get("highlights") if isinstance(body, dict) else {}
    cheapest = highlights.get("cheapest") if isinstance(highlights, dict) else None
    fastest = highlights.get("fastest") if isinstance(highlights, dict) else None
    if not isinstance(cheapest, dict):
        return None

    # Mapeo: previo "Económica" → cheapest; previo "Rápida" → fastest.
    prev_service = (shipping_meta.get("service_level") or "").strip().lower()
    chosen = cheapest
    chosen_service = "Económica"
    if prev_service in ("rápida", "rapida") and isinstance(fastest, dict):
        chosen = fastest
        chosen_service = "Rápida"

    # `total_price` viene como string formateado o número en cents.
    total_raw = chosen.get("total_price") or chosen.get("total")
    try:
        if isinstance(total_raw, (int, float)):
            shipping_cents = int(round(float(total_raw) * 100))
        else:
            cleaned = str(total_raw).replace("$", "").replace(".", "").replace(",", "").strip()
            shipping_cents = int(cleaned) * 100 if cleaned.isdigit() else 0
    except Exception:
        shipping_cents = 0
    if shipping_cents <= 0:
        logger.warning("[REQUOTE_LAZY] total_price inválido en cheapest=%s", chosen)
        return None

    carrier_name = str(chosen.get("carrier") or "Coordinadora").strip()
    rate_id = chosen.get("rate_id") or chosen.get("id")

    logger.info(
        "[REQUOTE_LAZY] conv=%s service=%s carrier=%s new_shipping_cents=%s "
        "(prev=%s)",
        conversation_id[:8], chosen_service, carrier_name, shipping_cents,
        shipping_meta.get("shipping_cents"),
    )
    return {
        "shipping_cents": shipping_cents,
        "carrier_name": carrier_name,
        "service_level": chosen_service,
        "rate_id": rate_id,
        "city": city_known,
    }


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

        # Rev. 104 (S14[known] fix) — prioridad de destino:
        #   1. cart.shipping_meta.city: si el cliente acaba de cambiar la
        #      ciudad post-cotización, el orchestrator ya invocó
        #      `cart_tool.set_shipping_city(new_city)` ANTES del dispatch.
        #      Respetar esa intención sobre la dirección guardada del
        #      contacto (caso known user que dice "cambia el envío a
        #      Medellín" cuando su address default es Bogotá).
        #   2. contact.address: fallback a dirección guardada del cliente.
        #   3. query_text + history: parsing explícito del inbound.
        #
        # Sin (1), un known user nunca podía cambiar ciudad: el tool
        # siempre defaulteaba a su address guardada.
        destination = None
        try:
            cart_row = (
                supabase.table("conversation_carts")
                .select("shipping_meta")
                .eq("conversation_id", conversation_id)
                .eq("status", "open")
                .limit(1).execute()
            )
            if cart_row.data:
                meta = cart_row.data[0].get("shipping_meta") or {}
                city_from_cart = (meta.get("city") or "").strip()
                if city_from_cart:
                    destination, _amb = _resolve_destination_from_conversation(
                        query_text=f"envío a {city_from_cart}",
                        recent_messages=[],
                    )
                    if destination:
                        logger.info(
                            "[SHIPPING_QUOTE] destino desde cart.shipping_meta.city=%s",
                            city_from_cart,
                        )
        except Exception as exc:
            logger.warning("[SHIPPING_QUOTE] cart shipping_meta lookup falló: %s", exc)

        if destination is None:
            contact_address = _get_contact_address(supabase, tenant_id, phone)
            destination = _coerce_destination(contact_address)

        ambiguous_city = None
        if destination is not None:
            recipient_phone = _get_contact_shipping_phone(supabase, tenant_id, phone)
            if recipient_phone:
                destination["phone"] = recipient_phone
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

        # Plan A.0.1 / ADR-0011 §6.5 — persistir city al cart en cuanto se
        # resuelve, no esperar al confirmar carrier. Sin esto, una recotización
        # lazy posterior (post add_item) no encuentra city en cart.shipping_meta
        # y debe caer a heurísticas de history-parsing (anti-Plan).
        try:
            _persist_destination_city_to_cart(
                supabase, tenant_id=tenant_id, conversation_id=conversation_id,
                destination=destination,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[SHIPPING_QUOTE] persistir city al cart falló conv=%s: %s",
                conversation_id[:8], exc,
            )

        # Rev. 81 — Si hay cart-en-DB con items, lo usamos como fuente de
        # verdad para peso/dims (cart-as-SoT). Esto evita doble confirmación
        # cuando el cliente ya consolidó su carrito en turnos previos.
        package_decision = _estimate_package_from_cart_if_available(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        if package_decision is None:
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

        # Persistir quoted_options en cart.shipping_meta para que el
        # `select_carrier` (agentic) pueda resolver el rate_id real cuando
        # el cliente elija "Económica"/"Rápida" en el siguiente turn.
        # Rev. 106 — fix RATE_ID_NOT_CACHED (conv 2eb3bb48). DB-first
        # Plan A.0.2: cross-path legacy↔agentic comparten misma fuente.
        try:
            from tools.cart_tool import (
                get_cart_with_items, set_quoted_options,
            )
            cart_row = get_cart_with_items(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
            )
            if cart_row and cart_row.get("id"):
                opts_to_persist: list[dict] = []
                seen_rate_ids: set[str] = set()
                for label_key, rate in (("cheapest", highlights.get("cheapest")),
                                        ("fastest",  highlights.get("fastest"))):
                    if not isinstance(rate, dict):
                        continue
                    rid = str(rate.get("rate_id") or rate.get("id") or "").strip()
                    if not rid or rid in seen_rate_ids:
                        continue
                    seen_rate_ids.add(rid)
                    total_raw = rate.get("total_price") or rate.get("total") or 0
                    try:
                        price_cents = int(float(total_raw) * 100)
                    except (TypeError, ValueError):
                        price_cents = 0
                    opts_to_persist.append({
                        "rate_id": rid,
                        "carrier": str(rate.get("carrier") or ""),
                        "service_level": str(rate.get("service") or ""),
                        "price_cents": price_cents,
                        "eta_date": str(
                            rate.get("delivery_estimate")
                            or rate.get("eta") or ""
                        ),
                        "currency": str(rate.get("currency") or "COP"),
                    })
                if opts_to_persist:
                    set_quoted_options(
                        supabase,
                        cart_id=cart_row["id"],
                        tenant_id=tenant_id,
                        options=opts_to_persist,
                    )
        except Exception as exc:
            logger.warning(
                "[SHIPPING_QUOTE] persist quoted_options falló: %s", exc,
            )

        return ShippingQuoteResult(handled=True, response_text=message)
    except Exception as exc:
        logger.error("Error en shipping_quote_tool tenant=%s: %s", tenant_id, exc, exc_info=True)
        return ShippingQuoteResult(
            handled=True,
            response_text="No pude cotizar el envio ahora mismo. Te apoyo con un asesor experto.",
            requires_human=True,
        )
