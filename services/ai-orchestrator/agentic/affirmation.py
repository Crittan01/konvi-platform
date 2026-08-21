"""Detección determinística de afirmación/negación es-CO en mensajes cortos.

Auditoría money-path 2026-08-21. Compartido por:
  • B6 — confirmación en dos turnos para cancelar una orden PAGADA
    (agentic/dispatcher.py + agentic/cancel_intent_resolver.py).
  • FIX5 — gate de confirmación del cliente antes de generar el link de pago
    (agentic/legacy_adapters/payment.py).

Diseño: alta precisión sobre recall. Un falso afirmativo mueve dinero real
(void de pago / link de cobro); un falso negativo solo vuelve a preguntar.
Por eso cualquier negación o calificador ("no", "aún no", "pero", "aunque")
descalifica la afirmación aunque empiece con "sí".
"""
from __future__ import annotations

import re
import unicodedata


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    """Minúsculas, sin diacríticos, sin puntuación, espacios colapsados."""
    base = _strip_diacritics((s or "").lower())
    base = re.sub(r"[^\w\s]", " ", base)  # puntuación → espacio
    return re.sub(r"\s+", " ", base).strip()


# Negación o calificador en cualquier parte del mensaje → NO es afirmación.
# "sí, pero...", "no sé", "aún no", "espera", "claro que no" caen aquí.
_NEGATION_RE = re.compile(
    r"\b(?:no|nunca|jamas|todavia|aun|tampoco|espera|esperate|pero|aunque|"
    r"cancela(?:r|me|lo|la)?|anula(?:r|me|lo|la)?)\b",
    re.IGNORECASE,
)

# Arranques afirmativos es-CO (mensaje corto). Se ancla al INICIO para que
# frases largas tipo "quisiera saber si..." no cuelen.
_AFFIRM_START_RE = re.compile(
    r"^(?:"
    r"si|sisas|ok|okay|dale|listo|listos|perfecto|perfecta|confirmo|confirmad[oa]|"
    r"correcto|de\s+acuerdo|bueno|vale|claro|va|hagale|adelante|procede|"
    r"acepto|por\s+supuesto|seguro|afirmativo|asi\s+es|eso\s+es|exacto|exactamente"
    r")\b",
    re.IGNORECASE,
)

# Respuestas explícitamente negativas (para cerrar confirmaciones pendientes
# con un acuse claro en vez de caer al flujo normal).
_NEGATIVE_START_RE = re.compile(
    r"^(?:no|noup|nop|negativo|mejor\s+no|todavia\s+no|aun\s+no|para|deten(?:lo)?|"
    r"dejalo|dejala|deja(?:lo|la)?\s+asi|olvidalo|olvidala|ni\s+loco)\b",
    re.IGNORECASE,
)

# Tope de longitud: la confirmación es una frase CORTA. Mensajes largos con
# "sí" embebido ("sí, pero además quería preguntar...") no son confirmación.
_MAX_AFFIRM_CHARS = 60


def is_affirmative(text: str) -> bool:
    """True si el mensaje es una afirmación corta estilo es-CO.

    Rechaza negaciones/calificadores en cualquier posición ("no sé",
    "aún no", "sí pero...") y mensajes largos con afirmación embebida.
    """
    norm = _norm(text or "")
    if not norm or len(norm) > _MAX_AFFIRM_CHARS:
        return False
    if _NEGATION_RE.search(norm):
        return False
    return bool(_AFFIRM_START_RE.match(norm))


def is_negative(text: str) -> bool:
    """True si el mensaje es una negación explícita corta ("no", "mejor no",
    "déjalo así"...). Se usa para cerrar la confirmación pendiente con acuse."""
    norm = _norm(text or "")
    if not norm or len(norm) > _MAX_AFFIRM_CHARS:
        return False
    return bool(_NEGATIVE_START_RE.match(norm))


# ── FIX5: confirmación tras el último resumen del bot ────────────────────────

# El resumen de pedido (prompt/states.py "📋 *Resumen del pedido* ... *TOTAL: $X*"
# y cart_render.py "TOTAL $X") siempre lleva "TOTAL" seguido del monto en pesos.
_SUMMARY_TOTAL_RE = re.compile(r"total\s*:?\s*\$", re.IGNORECASE)


def has_confirmation_after_summary(messages_desc: list[dict]) -> bool:
    """True si el cliente confirmó afirmativamente DESPUÉS del último
    resumen/total mostrado por el bot.

    `messages_desc`: mensajes recientes de la conversación en orden
    descendente (más nuevo primero), cada uno {direction, content}.

    Recorrido nuevos→viejos: si aparece un inbound afirmativo y MÁS ABAJO hay
    un resumen con total del bot, la confirmación es vigente. Si el resumen
    aparece primero (sin afirmación posterior), la última palabra sobre el
    total la tiene el bot y falta el "sí" del cliente (el total pudo cambiar
    después de aquel "sí" viejo). Sin resumen en la ventana → False
    (fail-closed: un "sí" sin total previo no confirma ninguna compra).
    """
    saw_affirmation = False
    for msg in messages_desc or []:
        if not isinstance(msg, dict):
            continue
        direction = str(msg.get("direction") or "").lower()
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        if direction == "outbound" and _SUMMARY_TOTAL_RE.search(content):
            return saw_affirmation
        if direction == "inbound" and is_affirmative(content):
            saw_affirmation = True
    return False
