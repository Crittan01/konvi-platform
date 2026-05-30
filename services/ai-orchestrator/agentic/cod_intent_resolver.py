"""Pre-LLM resolver determinístico: intent de pago contraentrega (COD).

Rev. 108 Fase B — el cliente menciona explícitamente que quiere pagar
al recibir / contraentrega / en efectivo al llegar. Detectamos antes del
LLM para:
  1. Validar runtime que el tenant tenga COD activo + al menos 1 carrier
     con `supports_cod=true`.
  2. Marcar la conversación con `payment_method_intent='cod'` para que
     downstream payment_link_tool tome el branch correcto (sin Wompi).
  3. Si el tenant NO ofrece COD → respuesta determinística inmediata
     "lo siento, solo aceptamos pago anticipado" sin gastar tokens LLM.

Patrón espejo de:
  • purchase_intent_resolver (intent="quiero comprar")
  • shipping_resolver       (intent="enviar a {ciudad}")
  • variant_continuation    (intent="el de 30g")

Frases capturadas (validadas con corpus muestral Colombia):
  • "pago contra entrega"
  • "pagar al recibir"
  • "pago al llegar"
  • "cobran al entregar"
  • "lo pago cuando llegue"
  • "cod"
  • "contraentrega"
  • "efectivo al recibirlo"
  • "pagar en mano"
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


# Patrones COD — capturan variaciones comunes en español Colombia.
# Diseño defensivo: alta precisión (evita falsos positivos en frases
# tipo "pago contra mis ahorros"). Cada pattern es un regex completo.
_COD_PATTERNS = (
    # "contraentrega" / "contra entrega" — palabra clave directa
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    # "COD" sigla — solo si está aislada (no "codigo")
    re.compile(r"\bcod\b", re.IGNORECASE),
    # "pago al recibir" / "pagar al recibir" / "pago cuando llegue"
    re.compile(
        r"\bpag[oa]r?\s+(?:al|cuando|en|el\s+momento\s+de)\s+"
        r"(?:recibi|lleg|entrega|recoger)",
        re.IGNORECASE,
    ),
    # "pago contra entrega" / "pagar contraentrega"
    re.compile(
        r"\bpag[oa]r?\s+(?:contra|en)?\s*entrega\b",
        re.IGNORECASE,
    ),
    # "cobran al entregar" / "cobran cuando entreguen"
    re.compile(
        r"\b(?:cobra|cobran|cobrar)\s+(?:al|cuando|en\s+el)\s+"
        r"(?:entrega|llega|recibi)",
        re.IGNORECASE,
    ),
    # "lo pago cuando me lo entreguen" / "pagar al destinatario"
    re.compile(
        r"\bpag[oa]r?\s+(?:al|cuando)\s+(?:me\s+)?(?:lo\s+)?"
        r"(?:lleg|entrega|destinatario|recib)",
        re.IGNORECASE,
    ),
    # "efectivo al recibir" / "en efectivo cuando llegue"
    re.compile(
        r"\b(?:efectivo|dinero|plata)\s+(?:al|cuando|en\s+el)\s+"
        r"(?:recibi|lleg|entrega)",
        re.IGNORECASE,
    ),
    # "pagar en mano" / "paga en mano"
    re.compile(r"\bpag[oa]r?\s+(?:en|de)\s+mano\b", re.IGNORECASE),
)


# Anti-patterns: frases que mencionan COD pero NO son intent positivo.
# Ej. cliente preguntando "¿aceptan pago contra entrega?" sí es intent.
# Ej. "no quiero pagar contra entrega" es intent NEGATIVO → descartar.
_NEGATION_PATTERNS = (
    re.compile(r"\bno\s+(?:quiero|deseo|me\s+gusta)\b", re.IGNORECASE),
    re.compile(r"\bprefiero\s+(?:pagar|el\s+pago)\s+(?:online|antes|ahora)\b", re.IGNORECASE),
    re.compile(r"\bmejor\s+(?:pago|pagar)\s+(?:online|antes|con\s+tarjeta)\b", re.IGNORECASE),
)


def detect_cod_intent(text: str) -> Optional[dict]:
    """Detecta si el cliente quiere pagar contraentrega.

    Args:
        text: mensaje raw del cliente.

    Returns:
        dict {"intent": "cod", "matched_pattern": <pattern_str>}
        si detecta intent COD positivo. None si no o si hay negación.

    Ejemplos:
        >>> detect_cod_intent("¿aceptan pago contra entrega?")
        {'intent': 'cod', 'matched_pattern': '\\bcontra[\\s\\-]?entrega\\b'}

        >>> detect_cod_intent("no, prefiero pagar online")
        None

        >>> detect_cod_intent("Hola, ¿cómo están?")
        None
    """
    if not text or not isinstance(text, str):
        return None
    normalized = _norm(text)
    if not normalized:
        return None

    # Negación primero — si el cliente explícitamente NO quiere COD,
    # no captura intent. Detección "alternativa después de negación"
    # SOLO si hay conector claro entre la negación y la mención COD:
    #   "no online, contraentrega" → válido (alternativa con coma)
    #   "no quiero contra entrega" → negación pura (sin conector)
    _ALTERNATIVE_CONNECTORS = re.compile(
        r"[,;]|\bsino\b|\bpero\b|\bmejor\b|\bprefiero\b",
    )

    for neg in _NEGATION_PATTERNS:
        neg_match = neg.search(normalized)
        if neg_match:
            # Buscar COD positivo después de la negación.
            for pat in _COD_PATTERNS:
                cod_match = pat.search(normalized)
                if cod_match and cod_match.start() > neg_match.end():
                    # Hay COD después de neg. Validar conector entre
                    # neg.end() y cod_match.start().
                    bridge = normalized[neg_match.end():cod_match.start()]
                    if _ALTERNATIVE_CONNECTORS.search(bridge):
                        return {
                            "intent": "cod",
                            "matched_pattern": pat.pattern,
                            "matched_text": cod_match.group(0),
                            "negation_then_alternative": True,
                        }
            # Sin conector claro → negación cancela COD intent.
            return None

    # Sin negación — buscar intent COD positivo.
    for pat in _COD_PATTERNS:
        match = pat.search(normalized)
        if match:
            return {
                "intent": "cod",
                "matched_pattern": pat.pattern,
                "matched_text": match.group(0),
            }

    return None


def detect_credit_intent(text: str) -> Optional[dict]:
    """Espejo: detecta intent explícito de pago anticipado.

    Útil cuando cliente compara modalidades. Si el cliente dice
    "prefiero pagar con tarjeta" → preference clara → forzamos
    branch credit aunque tenant tenga COD habilitado.

    Returns:
        dict {"intent": "credit"} si detecta preferencia explícita
        por pago anticipado. None si no.
    """
    if not text or not isinstance(text, str):
        return None
    normalized = _norm(text)

    credit_patterns = (
        re.compile(
            r"\bpag(?:o|ar)\s+(?:online|anticipa|con\s+tarjeta|"
            r"con\s+(?:pse|nequi|bancolombia|wompi)|antes|ahora|"
            r"por\s+adelantado)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:tarjeta|pse|nequi|bancolombia\s+transfer)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bpref(?:iero|erir[ií]a)\s+pag(?:o|ar)\s+(?:online|antes|ahora)\b",
            re.IGNORECASE,
        ),
    )

    for pat in credit_patterns:
        match = pat.search(normalized)
        if match:
            return {
                "intent": "credit",
                "matched_pattern": pat.pattern,
                "matched_text": match.group(0),
            }

    return None
