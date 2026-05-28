"""Pre-LLM resolver determinístico: intent de cotización de envío.

Bug runtime KAIU UAT E2 2026-05-24:
  Bot ya tiene cart con items.
  Cliente: "En esta ocasión envíalo a Medellín, es para un regalo"
  Gemini con 19 tools → STOP+empty (saturación SDK).
  Text-only retry recuperó "Voy a cotizar el envío a Medellín. Un momento..."
  EmptyPromiseInvariant atrapó (promesa sin quote_shipping ejecutado).
  Rewrite a CTA genérico "confirma esa ciudad" → cliente queda sin opciones.

Solución arquitectónica: cuando el cart tiene items + cliente menciona
ciudad colombiana inequívoca, bypaseamos Gemini y llamamos
quote_shipping(city) directo. Mismo patrón que purchase_intent_resolver
y variant_continuation.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", _strip_diacritics(s).lower()).strip()


# Lista de ciudades colombianas con población >100k (top 50). Permite
# match flexible — si el cliente dice "Medellin", "medellin", "Medellín".
# Aveonline acepta MAYÚSCULAS con formato "CIUDAD(DEPARTAMENTO)".
# Esta lista es SOLO para detectar intent; la normalización a formato
# Aveonline la hace `to_aveonline_city_format()` downstream.
_KNOWN_COLOMBIAN_CITIES = {
    "bogota", "bogota d.c", "bogota dc", "medellin", "cali", "barranquilla",
    "cartagena", "cucuta", "bucaramanga", "pereira", "santa marta",
    "ibague", "manizales", "monteria", "neiva", "soledad",
    "villavicencio", "soacha", "pasto", "armenia", "valledupar",
    "buenaventura", "palmira", "popayan", "tunja", "florencia",
    "sincelejo", "yopal", "riohacha", "tulua", "envigado",
    "itagui", "bello", "barrancabermeja", "girardot", "duitama",
    "san andres", "mocoa", "leticia", "quibdo", "san jose del guaviare",
    "inirida", "mitu", "puerto carreno", "arauca",
}


# Patrones para detectar intent de envío + ciudad.
# Cubre frases comunes en español Colombia:
#   "envíalo a Medellín" / "mándalo a Cali" / "para Bogotá"
#   "envío a Pereira" / "a Bucaramanga" / "manda esto a Manizales"
#   "en esta ocasión envíalo a Medellín"
_INTENT_TO_CITY_PATTERNS = (
    re.compile(
        r"\b(?:env[ií]a(?:lo|melo)?|m[áa]nda(?:lo|melo)?|env[ií]o|"
        r"manda(?:lo|melo)?|despach[oa]|env[ií]ar)\s+"
        r"(?:esto|el\s+pedido|esto\s+a)?\s*"
        r"(?:para\s+|a\s+|hasta\s+)?"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]{2,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:para|a|hasta|destino)\s+"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]{2,40})",
        re.IGNORECASE,
    ),
)


# Stop-words que terminan el nombre de la ciudad cuando se encuentran.
# Rev. 109 UAT live BUG 9: añadidos "no", "y", "pero", "sino", "mejor",
# para interpretar negaciones "a Medellín NO Bogotá" como solo Medellín.
_CITY_END_MARKERS = (
    "como", "por", "que", "porque", "es", "para",
    "favor", "porfa", "entonces", "gracias",
    "no", "y", "pero", "sino", "mejor", "ya", "claro", "okay", "ok",
)


def _extract_city_candidate(inbound_text: str) -> Optional[str]:
    """Busca un nombre de ciudad colombiana en el inbound.

    Retorna el nombre normalizado (sin tildes, lowercase) si encuentra
    match único en la lista de ciudades. None si no aplica o es ambiguo.
    """
    text = (inbound_text or "").strip()
    if not text or len(text) > 300:
        return None

    candidates: list[str] = []
    for pat in _INTENT_TO_CITY_PATTERNS:
        for m in pat.finditer(text):
            raw_city = m.group(1).strip()
            # Cortar en stop-marker.
            tokens = raw_city.split()
            cleaned_tokens = []
            for tok in tokens:
                if _norm(tok) in _CITY_END_MARKERS:
                    break
                cleaned_tokens.append(tok)
            if not cleaned_tokens:
                continue
            cleaned = " ".join(cleaned_tokens)
            cleaned_norm = _norm(cleaned)
            # Match contra catalog ciudades.
            for known in _KNOWN_COLOMBIAN_CITIES:
                if cleaned_norm == known or known in cleaned_norm:
                    candidates.append(known)
                    break

    if not candidates:
        return None
    # Si múltiples ciudades detectadas, ambiguo — delegar a Gemini.
    if len(set(candidates)) != 1:
        return None
    return candidates[0]


def try_resolve_shipping_intent(
    *,
    inbound_text: str,
    cart_has_items: bool,
) -> Optional[dict]:
    """Detecta intent de cotización de envío + ciudad determinística.

    Pre-condiciones:
      • Cart tiene items (cotizar sin cart no tiene sentido).
      • Cliente menciona ciudad colombiana conocida sin ambigüedad.

    Returns:
      dict {"city": str_normalizado} si match único, None si no aplica.
    """
    if not cart_has_items:
        return None
    city = _extract_city_candidate(inbound_text)
    if not city:
        return None
    # Capitalize para passing a quote_shipping (tool tolera).
    return {"city": city.title()}
