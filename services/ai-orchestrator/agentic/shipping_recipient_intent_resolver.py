"""Pre-LLM resolver determinístico: intent envío a tercero (BUG 37).

Rev. 109 P0 #4 — cuando el cliente dice "es para mi mamá", "envíalo a
mi hermana", "regalo para Juan", etc., los datos del DESTINATARIO deben
guardarse en cart.shipping_meta.recipient (cart-scope, orden específica),
NO en contacts.* del TITULAR WhatsApp. Habeas Data Ley 1581 prohíbe
sobrescribir datos del titular con datos de un tercero sin su consent.

Sin este resolver, el LLM agentic elegía el path familiar
`save_contact_field` y sobrescribía Cristian → María (caso UAT live
sesión 2026-05-28).

Patrón espejo de cod_intent_resolver / cancel_intent_resolver:
  • Detección por regex (alta precisión, falsos positivos = 0).
  • Si match → marca intent + extrae datos parseables del mensaje.
  • Dispatcher invoca tool set_shipping_recipient determinístico.

Frases capturadas (validadas con corpus español Colombia):
  • "es para mi mamá / hermana / papá / hermano / tía / novio / esposa"
  • "envíalo a [nombre]"
  • "es un regalo para [nombre]"
  • "para mi oficina"
  • "lo recibe [nombre]"

NO captura:
  • "es para mi" (sin tercero) — implica titular mismo
  • "lo quiero para mí" — titular mismo
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", _strip_diacritics(s).lower()).strip()


# Relaciones familiares / contextos terceros (alta confianza).
_THIRD_PARTY_NOUNS = (
    "mama", "mami", "madre", "papa", "papi", "padre",
    "hermana", "hermano", "tia", "tio", "abuela", "abuelo",
    "prima", "primo", "sobrina", "sobrino",
    "novia", "novio", "esposa", "esposo", "pareja", "amiga", "amigo",
    "jefa", "jefe", "colega", "compañera", "companera",
    "secretaria", "asistente",
    "oficina", "trabajo", "empresa", "casa de",
)


# Verbos/marcadores envío a tercero.
_RECIPIENT_INTENT_PATTERNS = (
    # "es para mi mama / mama / abuela / etc."
    re.compile(
        r"\bes\s+para\s+(?:mi|la|el|mis)\s+(?:"
        + "|".join(_THIRD_PARTY_NOUNS)
        + r")\b",
        re.IGNORECASE,
    ),
    # "envialo a [Nombre Apellido]" / "envia a [Nombre]"
    re.compile(
        r"\benv[ií]a(?:l[oa])?\s+(?:a|para)\s+(?:mi\s+)?(?:"
        + "|".join(_THIRD_PARTY_NOUNS)
        + r"|\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})",
        re.IGNORECASE,
    ),
    # "regalo para [Nombre]" / "es un regalo para mi mama"
    re.compile(
        r"\b(?:es\s+un\s+)?regalo\s+(?:para|de)\s+(?:mi\s+)?",
        re.IGNORECASE,
    ),
    # "lo recibe [Nombre]"
    re.compile(
        r"\blo\s+recibe\s+(?:mi\s+)?",
        re.IGNORECASE,
    ),
    # "para mi oficina / trabajo / empresa"
    re.compile(
        r"\bpara\s+(?:mi|la|el)\s+(?:oficina|trabajo|empresa|jefa|jefe)\b",
        re.IGNORECASE,
    ),
)


# Patterns de extracción de datos del receptor.
_NAME_PATTERN = re.compile(
    r"(?:mam[aá]|hermana|hermano|t[ií]a|t[ií]o|abuel[oa]|"
    r"prim[oa]|sobrin[oa]|novi[oa]|espos[oa]|amig[oa]|jef[ae]|"
    r"oficina|recibe|para|nombre[:\s]+|llamada)\s*:?\s*"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})",
    re.IGNORECASE,
)

_DOCUMENT_PATTERN = re.compile(
    r"\b(CC|CE|NIT|TI|PP)[:\s]*(\d{6,12})\b",
    re.IGNORECASE,
)

# Phone CO: 10 dígitos comenzando con 3, opcional +57 prefix.
_PHONE_PATTERN = re.compile(
    r"(?:\+?57\s*)?(?:\bcel(?:ular)?\s*[:.]?\s*)?"
    r"(\b3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b)",
    re.IGNORECASE,
)


@dataclass
class RecipientIntentMatch:
    """Resultado del detector. Todos los campos opcionales — el resolver
    extrae lo que puede; lo demás lo pide el bot turn-by-turn."""
    name: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    phone: Optional[str] = None
    address_raw: Optional[str] = None  # texto bruto para que LLM extraiga si quiere


def detect_recipient_intent(text: str) -> Optional[RecipientIntentMatch]:
    """Detecta intent envío a tercero. None si no aplica.

    True positives capturados:
      "Es para mi mamá: Maria Tobon, CC 51234567, Cel 3009876543"
      "Envíalo a mi hermana"
      "Regalo para mi novia"
      "Para mi oficina"
    """
    if not text or len(text) > 1000:
        return None
    # ¿Alguno de los patterns marca intent envío a tercero?
    has_intent = any(p.search(text) for p in _RECIPIENT_INTENT_PATTERNS)
    if not has_intent:
        return None

    # Extracción best-effort de campos. El bot pedirá lo que falte.
    name_match = _NAME_PATTERN.search(text)
    doc_match = _DOCUMENT_PATTERN.search(text)
    phone_match = _PHONE_PATTERN.search(text)

    return RecipientIntentMatch(
        name=name_match.group(1).strip() if name_match else None,
        document_type=doc_match.group(1).upper() if doc_match else None,
        document_number=doc_match.group(2) if doc_match else None,
        phone=(
            "+57 " + re.sub(r"[\s\-]", "", phone_match.group(1))
            if phone_match else None
        ),
        # address_raw: incluimos resto del texto post primer ":" para
        # que LLM o cart_tool resuelva.
        address_raw=None,
    )
