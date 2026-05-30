"""Rev. 91 — Extractores determinísticos de slots para el checkout form.

Cada extractor toma `text` y retorna el slot value o None. Los extractores
son intencionalmente conservadores (precision > recall): cuando devuelven
un valor, alta confianza; cuando devuelven None, el conductor delega al
campo extracted_* del LLM.

Reusan primitivas de orchestrator.py (regex de email, _extract_first_name,
_detect_building_type_from_text) y agregan parsers nuevos solo donde no
existen (document type+number, name from "soy X" pattern).

Tests: tests/test_rev91_slot_extractors_dump.py
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# ── Email ─────────────────────────────────────────────────────────────────
# Misma regex search-friendly que orchestrator._EMAIL_SEARCH_REGEX (línea 249).
# Se duplica para no crear dependencia circular con orchestrator.py al
# importar slot_extractors desde el mismo módulo.
_EMAIL_SEARCH_REGEX = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    flags=re.IGNORECASE,
)


def extract_email(text: str) -> Optional[str]:
    """Extrae el primer email válido del texto. Lowercased."""
    if not text:
        return None
    match = _EMAIL_SEARCH_REGEX.search(text)
    if not match:
        return None
    return match.group(0).strip().lower()


# ── Document (type + number) ──────────────────────────────────────────────
# Pares válidos: CC/CE/NIT/PP/TI seguidos de 6-12 dígitos (admite puntos
# como separadores de miles y espacio entre tipo y número).
_DOC_PAIR_REGEX = re.compile(
    r"\b(CC|CE|NIT|PP|TI)\s*[:.\-]?\s*(\d(?:[.\s]?\d){5,11})\b",
    flags=re.IGNORECASE,
)


def extract_document(text: str) -> Optional[tuple[str, str]]:
    """Extrae par (tipo, número) si encuentra patrón explícito.

    Retorna None si solo hay dígitos sin tipo (ambiguo).
    """
    if not text:
        return None
    match = _DOC_PAIR_REGEX.search(text)
    if not match:
        return None
    doc_type = match.group(1).upper().strip()
    raw_num = match.group(2)
    digits = re.sub(r"[\s.]", "", raw_num)
    if 6 <= len(digits) <= 12:
        return doc_type, digits
    return None


# Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv 099bb891):
# Cliente dice "Cedula de Ciudadania" SIN número → `extract_document`
# retorna None (regex exige par tipo+número). El LLM tampoco extrajo
# por variante coloquial. Conductor no enriquece → flow re-pregunta
# como si nada hubiera avanzado.
#
# Solución arquitectónica: extractor SEPARADO de tipo-solo. El conductor
# lo invoca como fallback cuando `extract_document` (par) retorna None
# y persiste parcialmente. El prompt contextual del FSM ya pide solo
# número en el siguiente turno cuando tipo está pero number falta.

# Variantes coloquiales de tipo (español CO).
_DOC_TYPE_VARIANTS_REGEX = re.compile(
    r"\b("
    r"cedula\s+de\s+ciudadania"      # "Cédula de Ciudadanía"
    r"|cedula\s+de\s+extranjeria"     # "Cédula de Extranjería"
    r"|cedula\s+extranjera"            # variante
    r"|tarjeta\s+de\s+identidad"       # TI completo
    r"|cedula"                          # "Cédula" / "cedula"
    r"|extranjeria"                    # "Extranjería" suelta
    r"|pasaporte|passport"             # PP
    r"|nit"                            # NIT
    r"|cc|ce|ti|pp"                    # siglas
    r")\b",
    flags=re.IGNORECASE,
)


def extract_document_type_only(text: str) -> Optional[str]:
    """Extrae SOLO el tipo de documento (sin número) si el cliente lo
    menciona con variante coloquial o sigla.

    Útil para slot-filling secuencial: cliente dice "Cédula" en un turno
    → persistimos tipo; siguiente turno cliente da el número → completa.
    El conductor invoca como fallback cuando `extract_document` (par
    completo) retorna None.

    Returns: "CC" | "CE" | "NIT" | "PP" | "TI" | None.
    """
    if not text:
        return None
    # Normalizar acentos para regex (idempotente).
    import unicodedata
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    match = _DOC_TYPE_VARIANTS_REGEX.search(norm)
    if not match:
        return None
    raw = match.group(1).lower().strip()
    # Mapeo a tipos canónicos. Orden importa (más específico primero
    # cuando hay solapamiento — ej. "cedula de extranjeria" debe vencer
    # a "cedula" sola).
    if "extranjer" in raw or raw == "ce":
        return "CE"
    if "tarjeta" in raw or raw == "ti":
        return "TI"
    if raw in {"pasaporte", "passport", "pp"}:
        return "PP"
    if raw == "nit":
        return "NIT"
    if "cedula" in raw or raw == "cc":
        return "CC"
    return None


# ── Name (patrón "soy X" / "me llamo X") ──────────────────────────────────
# Conservador: requiere preámbulo "soy" / "me llamo" / "mi nombre es"
# seguido de 1-4 tokens capitalizados o lowercase. Evita falsos positivos
# tipo "Sí, esa opción" → "Sí" como nombre.
_NAME_PREAMBLE_REGEX = re.compile(
    r"\b(?:soy|me\s+llamo|mi\s+nombre\s+es)\s+"
    r"([A-Za-zÁÉÍÓÚáéíóúÑñ]+(?:\s+[A-Za-zÁÉÍÓÚáéíóúÑñ]+){0,3})",
    flags=re.IGNORECASE,
)
_NAME_STOPWORDS = frozenset({
    "tu", "tu", "el", "la", "los", "las", "un", "una", "que", "de", "en",
    "para", "por", "y", "o", "no", "si", "mi", "su", "tus", "sus",
})


def extract_name(text: str) -> Optional[str]:
    """Extrae nombre de patrones explícitos. Title-cased."""
    if not text:
        return None
    match = _NAME_PREAMBLE_REGEX.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    tokens = [t for t in raw.split() if t.lower() not in _NAME_STOPWORDS]
    if not tokens:
        return None
    return " ".join(tok.title() for tok in tokens[:4])


# ── Address (street + city + building_type) ───────────────────────────────
# Patrón de calle: "calle/cra/carrera/dg/diagonal/transversal" + número
_STREET_REGEX = re.compile(
    r"\b(?:calle|cra|carrera|cl|kr|dg|diagonal|tv|transversal|av|avenida)"
    r"\.?\s*[\w\s\.\-#°ºsur(?:nort?e)]*?(?=\s*(?:,|$|\bbarrio|\bbogot|\bmedell|\bcali))",
    flags=re.IGNORECASE,
)

_CITY_REGEX = re.compile(
    r"\b(bogot[aá]|medell[ií]n|cali|barranquilla|cartagena|bucaramanga|"
    r"pereira|manizales|ibagu[eé]|santa marta|c[uú]cuta|monter[ií]a|"
    r"villavicencio|pasto|neiva|armenia|tunja|popay[aá]n|valledupar|"
    r"sincelejo|riohacha)\b",
    flags=re.IGNORECASE,
)


def extract_city(text: str) -> Optional[str]:
    """Extrae ciudad de Colombia mencionada. Title-cased."""
    if not text:
        return None
    match = _CITY_REGEX.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    # Normalizar: "Bogotá" → "Bogotá", "bogota" → "Bogotá".
    base = unicodedata.normalize("NFKD", raw.lower())
    folded = "".join(c for c in base if not unicodedata.combining(c))
    canonical = {
        "bogota": "Bogotá", "medellin": "Medellín", "cali": "Cali",
        "barranquilla": "Barranquilla", "cartagena": "Cartagena",
        "bucaramanga": "Bucaramanga", "pereira": "Pereira",
        "manizales": "Manizales", "ibague": "Ibagué",
        "santa marta": "Santa Marta", "cucuta": "Cúcuta",
        "monteria": "Montería", "villavicencio": "Villavicencio",
        "pasto": "Pasto", "neiva": "Neiva", "armenia": "Armenia",
        "tunja": "Tunja", "popayan": "Popayán", "valledupar": "Valledupar",
        "sincelejo": "Sincelejo", "riohacha": "Riohacha",
    }
    return canonical.get(folded, raw.title())


def extract_street(text: str) -> Optional[str]:
    """Extrae fragmento que parece dirección (calle/carrera + número).

    Heurística simple: empieza con palabra-clave de vía, termina antes de
    coma o palabra de ciudad. Best effort — el LLM suele parsear mejor
    direcciones complejas.
    """
    if not text:
        return None
    match = _STREET_REGEX.search(text)
    if not match:
        return None
    raw = match.group(0).strip(" .,")
    return raw.title() if raw else None


# ── Building type (re-export para conveniencia) ───────────────────────────
# `_detect_building_type_from_text` vive en orchestrator.py:1776. Importarla
# aquí crearía ciclo. El conductor importa ambos módulos y compone.


# ── Slot extraction multi-pass (alto nivel) ───────────────────────────────

def extract_all_slots(text: str) -> dict:
    """Corre todos los extractores determinísticos sobre el inbound.

    Retorna dict con campos populated solo si el extractor encontró match.
    Campos posibles: email, name, document_type, document_number,
    address.street, address.city.

    El building_type lo resuelve el conductor (necesita
    `_detect_building_type_from_text` de orchestrator).
    """
    out: dict = {}
    if not text:
        return out

    email = extract_email(text)
    if email:
        out["email"] = email

    name = extract_name(text)
    if name:
        out["name"] = name

    doc = extract_document(text)
    if doc:
        out["document_type"], out["document_number"] = doc
    else:
        # Sem 7 F2 cierre 2026-05-21 — slot-filling secuencial: si no hay
        # par completo, intentar extraer SOLO el tipo (cliente dice
        # "Cédula de Ciudadanía" sin número). El conductor persiste
        # parcial; el prompt contextual pide solo el número en el
        # siguiente turno.
        doc_type_only = extract_document_type_only(text)
        if doc_type_only:
            out["document_type"] = doc_type_only

    city = extract_city(text)
    street = extract_street(text)
    address: dict = {}
    if street:
        address["street"] = street
    if city:
        address["city"] = city
    if address:
        out["address"] = address

    return out
