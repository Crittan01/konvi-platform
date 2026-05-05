"""Invariantes de outbound — reglas determinísticas hard-coded (rev. 104).

A diferencia de heurísticas LLM, estos invariantes son **garantías** que aplican
SIEMPRE a la salida del bot, independientemente de qué texto produjo el LLM.

Invariantes implementados:
  • F0-6 / BUG-5 — `assert_summary_shown_before_link`: link Wompi requiere
    resumen previo en últimos N outbounds.
  • F1-9 / BUG-8 — `assert_no_pii_request_pre_consent`: el bot NO puede
    pedir PII (nombre, email, documento, dirección) si el contacto NO ha
    dado consent (Habeas Data Ley 1581 art. 9).
"""
from __future__ import annotations

import re
from typing import Optional

# Marker tolerante a variaciones — emoji bandeja (`📋`) o phrase canónica.
_SUMMARY_MARKERS = ("📋", "*resumen", "resumen de tu pedido")
_WOMPI_LINK_PATTERN = re.compile(
    r"https?://[^\s]*(?:checkout\.wompi|wompi\.co)[^\s]*",
    re.IGNORECASE,
)


def text_contains_wompi_link(text: str) -> bool:
    return bool(_WOMPI_LINK_PATTERN.search(text or ""))


def text_is_summary(text: str) -> bool:
    """True si el texto es un resumen del pedido (con `📋` o phrase canónica)."""
    if not text:
        return False
    low = text.lower()
    return any(m in text or m in low for m in _SUMMARY_MARKERS)


def last_outbound_was_summary(history: list[dict], lookback: int = 5) -> bool:
    """True si entre los últimos N outbounds del bot hay un resumen.

    `history` es lista ordenada cronológicamente (oldest first). Recorre desde
    el más reciente hacia atrás hasta `lookback` outbounds.
    """
    if not history:
        return False
    seen_outbound = 0
    for msg in reversed(history):
        direction = str(msg.get("direction") or "").strip().lower()
        if direction != "outbound":
            continue
        seen_outbound += 1
        if seen_outbound > lookback:
            break
        content = str(msg.get("content") or "")
        if text_is_summary(content):
            return True
    return False


# ─── Invariant F1-9 / BUG-8 ──────────────────────────────────────────────────
# El bot NO debe pedir PII (nombre, email, documento, dirección) si el contacto
# aún no ha dado consent. Habeas Data Ley 1581 art. 9 — el responsable solo
# puede recolectar datos personales con autorización previa, expresa, informada.

# Frases canónicas que el bot usa para pedir PII (cubren el template oficial
# y variantes naturales del LLM).
_PII_REQUEST_PHRASES = (
    # Email
    "cuál es tu correo", "cual es tu correo",
    "compárteme tu correo", "comparteme tu correo",
    "tu email", "tu correo electrónico", "tu correo electronico",
    # Nombre
    "nombre completo", "compárteme tu nombre", "comparteme tu nombre",
    "cómo te llamas", "como te llamas", "cuál es tu nombre",
    "confirmas tu nombre",
    # Documento
    "tipo de documento", "tu cédula", "tu cedula",
    "cédula (cc)", "cedula (cc)", "tu nit",
    "documento de identidad", "número de documento",
    # Dirección
    "tu dirección de", "tu direccion de",
    "compárteme la dirección", "comparteme la direccion",
    "para completar la dirección", "para completar la direccion",
    "donde te enviamos",
)


def text_requests_pii(text: str) -> bool:
    """True si el texto contiene una frase que pide PII al cliente."""
    if not text:
        return False
    low = text.lower()
    return any(phrase in low for phrase in _PII_REQUEST_PHRASES)


def assert_no_pii_request_pre_consent(
    candidate_text: str,
    contact_consent_given: bool,
) -> Optional[str]:
    """Invariant — devuelve `None` si OK, o motivo si viola.

    Habeas Data Ley 1581 art. 9: el bot NO puede pedir PII si el contacto
    no ha dado consent activo. Si lo hace, hay riesgo de violación legal.

    Args:
      candidate_text: texto que el bot está por enviar.
      contact_consent_given: estado actual de `contacts.consent_given`.
    """
    if contact_consent_given:
        return None  # consent activo, PII permitido
    if not text_requests_pii(candidate_text):
        return None  # no pide PII, invariant no aplica
    return (
        "Outbound pide PII (nombre/email/documento/dirección) sin consent "
        "del titular — invariant 'no-pii-pre-consent' violado (Ley 1581 art. 9)."
    )


# ─── Invariant SMELL-1 — saludo time-aware en primer outbound ───────────────
# El bot debe usar saludo time-aware ("Buenos días/tardes/noches") en lugar
# de "¡Hola!" genérico cuando es el primer outbound de la conversación. Refleja
# la hora local Colombia (UTC-5) y/o espeja el saludo del cliente si éste usó
# uno time-specific.

# Bloque de saludos time-specific que el cliente puede usar (normalizado
# a lowercase). Si los detectamos en el inbound, los espejamos.
_CLIENT_TIME_GREETINGS = (
    "buenos dias", "buenos días", "buen dia", "buen día",
    "buenas tardes", "buena tarde",
    "buenas noches", "buena noche",
)

# Patrón saludo (genérico "Hola" o time-specific) al inicio de un outbound.
# Captura: opcional `¡` + word + opcional puntuación trailing (`!` `,` `.`).
# group(1) = word del saludo. group(2) = puntuación trailing si existe.
_OPENING_GREETING_PATTERN = re.compile(
    r"^[\s¡!]*"
    r"(hola|buenos\s+d[ií]as?|buen\s+d[ií]a|buenas\s+tardes?|buena\s+tarde|"
    r"buenas\s+noches?|buena\s+noche)"
    r"([!,.])?",
    re.IGNORECASE,
)

# Mapping de saludo detectado → forma canónica capitalizada.
def _canonicalize_greeting(raw: str) -> str:
    norm = raw.lower().strip()
    if norm.startswith(("buenos dia", "buenos día", "buen dia", "buen día")):
        return "Buenos días"
    if norm.startswith(("buenas tarde", "buena tarde")):
        return "Buenas tardes"
    if norm.startswith(("buenas noche", "buena noche")):
        return "Buenas noches"
    return "Hola"


def _is_first_outbound(history: list[dict]) -> bool:
    """True si este es el primer outbound de la conversación (no hay
    outbounds previos en el history)."""
    if not history:
        return True
    return not any(
        str(m.get("direction") or "").lower() == "outbound"
        for m in history
    )


def assert_time_aware_greeting_first_outbound(
    candidate_text: str,
    history: list[dict],
    *,
    server_time_greeting: str,
) -> Optional[tuple[str, str]]:
    """Invariant — alinea el saludo del primer outbound a server_time.

    server_time_greeting es la AUTORIDAD ÚNICA del saludo. NO se espeja al
    cliente. NO se respeta la elección del LLM. Si el bot saludó con algo
    distinto al server_time_greeting, se reescribe.

    Args:
      candidate_text: texto que el bot está por enviar.
      history: mensajes previos (oldest first).
      server_time_greeting: saludo canónico según hora local Colombia
        ("Buenos días" / "Buenas tardes" / "Buenas noches" / "Hola").

    No dispara cuando:
      • No es primer outbound de la conversación.
      • Bot no abre con saludo (ej. "Claro,", "Listo,").
      • Bot ya emitió el server_time_greeting (idempotencia).
      • server_time_greeting es "Hola" o vacío.
    """
    if not candidate_text:
        return None
    if not _is_first_outbound(history):
        return None
    if not server_time_greeting or server_time_greeting.lower() == "hola":
        return None

    match = _OPENING_GREETING_PATTERN.match(candidate_text)
    if not match:
        return None  # bot no abrió con saludo (ej. con conector "Claro,").

    bot_greeting = _canonicalize_greeting(match.group(1))
    if bot_greeting == server_time_greeting:
        return None  # ya correcto

    # Construir rewrite: server_time_greeting + puntuación (preservar la
    # del input o `!` como default cordial).
    matched_str = match.group(0)
    trailing_punct = match.group(2) or "!"
    replacement = f"{server_time_greeting}{trailing_punct}"
    rewritten = replacement + candidate_text[len(matched_str):]
    violation = (
        f"Outbound primer mensaje saluda '{bot_greeting}' cuando "
        f"server_time pide '{server_time_greeting}' — invariant "
        f"'time-aware-greeting' violado."
    )
    return (violation, rewritten)


# ─── Invariant SMELL-3 — conector cordial para pregunta directa ─────────────
# Operacionaliza la regla del prompt `_HUMAN_STYLE_GUIDE`: si el cliente
# abre con pregunta directa (sin saludo), el bot DEBE abrir con un conector
# cordial ("Claro,", "Listo,", "Por supuesto,", "Te cuento,", "Con gusto,").
# El LLM a veces va directo al contenido — este invariant lo corrige.

_DIRECT_QUESTION_OPENERS = (
    "qué", "que", "cuál", "cual", "cómo", "como",
    "cuándo", "cuando", "dónde", "donde",
    "quién", "quien", "cuánto", "cuanto",
    "por qué", "por que",
)

_GREETING_OPENERS = (
    "hola", "buenos", "buenas", "buen día", "buen dia",
    "qué tal", "que tal", "saludos",
)

_CORDIAL_CONNECTOR_OPENERS = (
    # Neutros (funcionan con afirmación y con denial).
    "mira", "te cuento", "verás", "veras", "te explico", "bueno",
    # Afirmativos (suenan bien con respuestas positivas; en denials
    # pueden sonar incoherentes — el invariant prefiere neutros como
    # rewrite, pero los acepta como apertura válida del LLM).
    "claro", "listo", "perfecto", "por supuesto", "con gusto",
    "entendido", "genial",
)

# Conectores rotativos para el rewrite — neutros, funcionan tanto con
# respuestas afirmativas ("Mira, aceptamos devoluciones...") como con
# denials ("Mira, no comercializamos medicamentos..."). Diversidad por
# hash determinístico del candidate_text — misma respuesta siempre genera
# el mismo conector, pero conv→conv varía.
_REWRITE_CONNECTORS = ("Mira,", "Te cuento,", "Verás,")


def _first_inbound_is_direct_question(history: list[dict]) -> bool:
    """True si el primer inbound del cliente fue pregunta directa sin saludo."""
    if not history:
        return False
    inbounds = [
        m for m in history
        if str(m.get("direction") or "").lower() == "inbound"
    ]
    if not inbounds:
        return False
    first = str(inbounds[0].get("content") or "").strip().lower()
    if not first:
        return False
    # Si arranca con saludo, NO es pregunta directa pura.
    if any(first.startswith(g) for g in _GREETING_OPENERS):
        return False
    # Sí lo es si arranca con question word OR termina con `?`.
    starts_question = any(first.startswith(q) for q in _DIRECT_QUESTION_OPENERS)
    return starts_question or first.endswith("?")


def _bot_opens_with_greeting_or_connector(candidate_text: str) -> bool:
    """True si el outbound abre con saludo time-aware o conector cordial."""
    if not candidate_text:
        return False
    norm = candidate_text.lstrip().lower()
    for opener in (*_GREETING_OPENERS, *_CORDIAL_CONNECTOR_OPENERS):
        if norm.startswith(opener):
            return True
    return False


def assert_cordial_connector_for_direct_question(
    candidate_text: str,
    history: list[dict],
) -> Optional[tuple[str, str]]:
    """Invariant — devuelve `(violation, rewrite_text)` si viola, None si OK.

    Si el cliente abrió con pregunta directa (sin saludo) y el bot va
    directamente al contenido sin un conector cordial, prefija "Claro, ".
    Operacionaliza la regla del prompt `_HUMAN_STYLE_GUIDE`.

    Solo aplica al primer outbound de la conversación.
    """
    if not candidate_text:
        return None
    if not _is_first_outbound(history):
        return None
    if not _first_inbound_is_direct_question(history):
        return None
    if _bot_opens_with_greeting_or_connector(candidate_text):
        return None

    # Rewrite determinístico: prefijar conector neutro (rotativo por hash)
    # + lowercase la primera letra del contenido original. Los conectores
    # son neutros — funcionan tanto con afirmación como con denial, evitando
    # "Claro, no comercializamos..." (incoherente).
    connector = _REWRITE_CONNECTORS[hash(candidate_text) % len(_REWRITE_CONNECTORS)]
    first_char = candidate_text[0]
    rest = candidate_text[1:]
    rewritten = f"{connector} {first_char.lower()}{rest}"
    violation = (
        "Outbound primer mensaje va directo a contenido cuando el cliente "
        "abrió con pregunta directa sin saludo — invariant "
        "'cordial-connector-for-direct-question' violado."
    )
    return (violation, rewritten)


def assert_summary_shown_before_link(
    candidate_text: str,
    history: list[dict],
    *,
    lookback: int = 5,
) -> Optional[str]:
    """Invariant principal — devuelve `None` si OK, o un mensaje de motivo
    si la regla falla.

    Caller del invariant: si retorna no-None, debe rechazar/reescribir el
    outbound antes de enviarlo al cliente. La acción de rewrite es
    responsabilidad del caller (ej: forzar render del resumen primero).

    Args:
      candidate_text: el texto que el bot está por enviar.
      history: mensajes previos de la conversación (oldest first).
      lookback: cuántos outbounds previos contar como "reciente" (default 5).
    """
    if not text_contains_wompi_link(candidate_text):
        return None  # No es un envío de link, invariant no aplica.
    if last_outbound_was_summary(history, lookback=lookback):
        return None  # OK: hubo resumen reciente.
    return (
        "Outbound con link Wompi sin resumen previo en los últimos "
        f"{lookback} outbounds — invariant 'resumen-before-link' violado."
    )
