"""Content safety — datos sensibles + crisis de salud mental.

Rev. 104 (F1-1 batch 2) — extraído de orchestrator.py.

Cobertura:
  • **Crisis de salud mental** (P0): autolesión / suicidio. Escalación
    INMEDIATA con mensaje de seguridad. Lista conservadora; falsos
    positivos son mejor que falsos negativos en este caso.
  • **Datos sensibles de pago**: CVV o número de tarjeta enviados al chat.
    Wompi maneja PAN en su widget seguro — el chat NO debe procesar PAN.

Public API:
  • `detect_mental_health_crisis(text) -> bool`
  • `detect_sensitive_payment_data(text) -> tuple[bool, reason]`
  • Constantes: `MENTAL_HEALTH_CRISIS_PHRASES`.

Tests: `tests/test_safety_content_safety.py`.
"""
from __future__ import annotations

import re
import unicodedata as _ud


# ─── Mental health crisis ────────────────────────────────────────────────────

MENTAL_HEALTH_CRISIS_PHRASES: tuple[str, ...] = (
    "me quiero matar", "me voy a matar", "quiero matarme",
    "voy a suicidarme", "suicidarme", "suicidio",
    "voy a morir", "quiero morir", "no quiero vivir", "no quiero seguir viviendo",
    "no quiero seguir aqui",  # _normalize strip accents → "aqui"
    "hacerme dano", "hacer dano", "hacerme daño", "hacer daño",
    "lastimarme", "cortarme",
    "no aguanto mas",
    "acabar con mi vida", "acabar con todo",
    "me quitare la vida",
    "pensamientos suicidas", "tentado a suicidarme",
)


# ─── Sensitive payment data (PAN + CVV) ──────────────────────────────────────

# CVV explícito: keyword + hasta 6 chars no-dígitos + 3-4 dígitos.
# Cubre "cvv 123", "cvv es 123", "cvc: 456", "código de seguridad es 789".
_CVV_RE = re.compile(
    r"(?:cvv|cvc|cvn|c[oó]digo\s+de\s+seguridad)\D{0,6}\d{3,4}",
    re.IGNORECASE,
)

# Tarjeta de crédito: secuencia de 13-19 dígitos consecutivos posiblemente
# separados por espacios/guiones. Cédulas colombianas son 8-12 dígitos →
# no gatillarán este detector.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)")


# ─── Helper interno ──────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase + sin acentos + espacios colapsados (replica text_utils)."""
    if not text:
        return ""
    norm = _ud.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(norm.lower().split())


# ─── Public detectors ────────────────────────────────────────────────────────

def detect_mental_health_crisis(text: str) -> bool:
    """True si el texto sugiere crisis de salud mental (autolesión / suicidio).

    Diseño conservador: la prioridad es NO ignorar un caso real. Falsos
    positivos derivan en escalación humana, que el agente puede manejar
    correctamente. Falsos negativos son inaceptables (riesgo de vida).
    """
    if not text:
        return False
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in MENTAL_HEALTH_CRISIS_PHRASES)


def detect_sensitive_payment_data(text: str) -> tuple[bool, str]:
    """True si el cliente envió datos sensibles que NO deben procesarse en chat.

    Returns:
        (detected, reason) — `reason` describe qué tipo se detectó para log.

    NOTA: el sistema sí pide y guarda `document_number` (CC), eso es
    aceptable y necesario. Lo que NO debe pasar:
      • Números de tarjeta de crédito en chat (Wompi widget seguro).
      • CVV en chat.
      • Cuentas bancarias completas en chat.
    """
    if not text:
        return False, ""
    if _CVV_RE.search(text):
        return True, "cvv_detected"
    if _CARD_RE.search(text):
        return True, "credit_card_pattern"
    return False, ""
