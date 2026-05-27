"""Pre-LLM resolver determinístico: intent de consent Habeas Data.

Rev. 108 fix arquitectónico — el LLM NO siempre llama `record_consent`
tras "Sí acepto" del cliente, causando loops infinitos donde:
  1. Bot pide consent.
  2. Cliente: "Sí acepto" / "Acepto" / "OK".
  3. LLM intenta pedir PII pero record_consent NO se llamó.
  4. Invariant `no-pii-pre-consent` detecta inconsistencia y rewrite a
     pedir consent OTRA VEZ.
  5. Loop.

Solución: detector pre-LLM determinístico que detecta afirmaciones de
consent DESPUÉS de que el bot las haya pedido. Si match → marca
contact.consent_given=True directamente + audit log, sin depender del LLM.

Patrón espejo de `cod_intent_resolver.py`. Misma filosofía: determinismo
en steps críticos del flow, LLM solo para natural language gloss.

Disparadores:
  - Bot del turno anterior pidió consent (mensajes con "consent",
    "autorización", "datos personales", "Habeas Data", etc.)
  - Cliente respondió afirmativamente ("Sí", "Sí acepto", "Acepto",
    "Estoy de acuerdo", "OK", etc.)
  - Contact existe (resuelto por dispatcher).

Output: mismo formato que cod_intent_resolver — dict con intent + match.
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


# Patrones afirmativos comunes en español Colombia.
# Diseño: tolerantes a puntuación intermedia ("Sí, acepto" / "Sí. Acepto").
_AFFIRMATIVE_PATTERNS = (
    # Forma corta: "Sí" / "Si" / "Sí." / "Sí!" (solo o al inicio)
    re.compile(r"^\s*si\s*[\.\!\?,]*\s*$", re.IGNORECASE),
    # "Sí acepto" / "Si acepto" / "Sí, acepto" — coma opcional intermedia
    re.compile(r"\bsi\s*[,;]?\s+acepto\b", re.IGNORECASE),
    # "Acepto" / "Acepto." (puede venir solo)
    re.compile(r"^\s*acepto\s*[\.\!\?,]*\s*$", re.IGNORECASE),
    # "Estoy de acuerdo" / "De acuerdo"
    re.compile(r"\bde\s+acuerdo\b", re.IGNORECASE),
    # "Está bien" / "Esta bien"
    re.compile(r"\bes(?:ta|t[áa])\s+bien\b", re.IGNORECASE),
    # "OK" / "Ok" / "Vale"
    re.compile(r"^\s*(?:ok|vale|listo|bueno)\s*[\.\!\?,]*\s*$", re.IGNORECASE),
    # "Autorizo" formal — chequeo de negación previa se hace por orden
    # de aplicación: NEGATIVE_PATTERNS corren ANTES de AFFIRMATIVE, así
    # "no te autorizo" matcha primero como negative y no llega aquí.
    re.compile(r"\b(?:autorizo|los?\s+autorizo)\b", re.IGNORECASE),
    # "Claro" / "Por supuesto" / "Dale" (común Colombia)
    re.compile(r"^\s*(?:claro|por\s+supuesto|dale)\s*[\.\!\?,]*\s*$", re.IGNORECASE),
)


# Patrones negativos — si match, NO es consent positive.
# Diseño: tolerantes a palabras intermedias ("no te autorizo" / "no los autorizo").
_NEGATIVE_PATTERNS = (
    re.compile(r"^\s*no\s*[\.\!\?,]*\s*$", re.IGNORECASE),
    re.compile(r"\bno\s+\w*\s*acepto\b", re.IGNORECASE),
    # "no autorizo" / "no te autorizo" / "no los autorizo"
    re.compile(r"\bno\s+(?:\w{1,5}\s+)?(?:autorizo|estoy\s+de\s+acuerdo)\b", re.IGNORECASE),
    re.compile(r"\b(?:rechazo|me\s+niego)\b", re.IGNORECASE),
)


# Patrones del outbound anterior del bot que indican pregunta de consent.
_BOT_ASKED_CONSENT_PATTERNS = (
    re.compile(r"autoriz[oae]?", re.IGNORECASE),
    re.compile(r"\bconsent", re.IGNORECASE),
    re.compile(r"\busar\s+tus?\s+datos\b", re.IGNORECASE),
    re.compile(r"\b(?:habeas\s+data|ley\s+1581)\b", re.IGNORECASE),
    re.compile(r"\bestás?\s+de\s+acuerdo\b", re.IGNORECASE),
)


def detect_consent_intent(
    text: str,
    bot_last_outbound: Optional[str] = None,
) -> Optional[dict]:
    """Detecta si el cliente está afirmando o negando consent.

    Args:
        text: mensaje raw del cliente.
        bot_last_outbound: último mensaje del bot, para validar contexto
            (debe haber pedido consent recientemente).

    Returns:
        dict con intent ('consent_granted' | 'consent_denied') + match info,
        o None si no aplica el contexto o no hay match.

    Ejemplos:
        >>> detect_consent_intent("Sí acepto", "Me autorizas a usar tus datos?")
        {'intent': 'consent_granted', ...}

        >>> detect_consent_intent("No, gracias", "Me autorizas a usar tus datos?")
        {'intent': 'consent_denied', ...}

        >>> detect_consent_intent("Sí", "Hola cómo estás?")
        None  # bot NO pidió consent, no aplicable
    """
    if not text or not isinstance(text, str):
        return None

    # Contexto: bot debe haber pedido consent en su mensaje anterior.
    # Si no tenemos bot_last_outbound, asumimos contexto válido (caller
    # responsabilidad de aplicar solo cuando makes sense).
    if bot_last_outbound is not None:
        bot_asked = any(
            p.search(bot_last_outbound) for p in _BOT_ASKED_CONSENT_PATTERNS
        )
        if not bot_asked:
            return None

    normalized = _norm(text)
    if not normalized:
        return None

    # Negative first — más explícito.
    for pat in _NEGATIVE_PATTERNS:
        if pat.search(normalized):
            return {
                "intent": "consent_denied",
                "matched_pattern": pat.pattern,
                "matched_text": text[:80],
            }

    # Affirmative.
    for pat in _AFFIRMATIVE_PATTERNS:
        if pat.search(normalized):
            return {
                "intent": "consent_granted",
                "matched_pattern": pat.pattern,
                "matched_text": text[:80],
            }

    return None
