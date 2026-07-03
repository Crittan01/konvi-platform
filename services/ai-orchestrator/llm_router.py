"""
Model router — Rev. 81 (model routing tier).

Clasifica intent del cliente en `simple` vs `transactional` y decide qué
modelo Gemini usar como primario:

  simple        → flash-lite primario (cheap), flash fallback.
  transactional → flash primario (precision), flash-lite fallback.

Heurística determinística (cero costo extra, no llama LLM): regex/keywords
+ FSM state. Si fallamos clasificación, la cascada nos cubre porque
ambos modelos están disponibles.

Uso:
    from llm_router import classify_intent, model_pair_for

    intent = classify_intent(query, fsm_state, history)
    primary, fallback = model_pair_for(intent)
    cascade = generate_with_cascade(invoke, primary_model=primary,
                                     fallback_model=fallback)

Costos (referencia Gemini 2.5 — reales pueden variar):
  flash:      ~$0.30 input / $2.50 output por 1M tokens.
  flash-lite: ~$0.10 input / $0.40 output por 1M tokens (3-6x cheaper).

Estimación: 70% de turnos en chat-commerce son simples (saludos, FAQ,
catálogo, info). Routing reduce costos ~50-60% sin perder calidad
transaccional.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("orchestrator.router")


# ─── Constantes de clasificación ─────────────────────────────────────────────

# Estados FSM transaccionales (capturando datos / pago / confirmación).
# Si estamos en cualquiera de estos, usamos flash sí o sí — la calidad de
# extracción multi-campo y JSON estructurado es crítica.
TRANSACTIONAL_FSM_STATES = frozenset({
    "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
    "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
    "READY_FOR_SUMMARY", "AWAITING_ORDER_CONFIRMATION",
})

# Tokens léxicos que indican intent transaccional aunque el FSM aún no
# haya avanzado. Si el cliente dice "quiero comprar", "agrega al carrito",
# "cuál es el envío", debemos usar flash para no fallar la conversión.
_TRANSACTIONAL_TOKENS_RE = re.compile(
    r"\b("
    r"comprar|comprare|compraría|compraria|"
    r"adquirir|adquiero|"
    r"pedir|pedido|pedidos|"
    r"agregar|añadir|anadir|"
    r"deseo|quiero|necesito|"
    r"carrito|"
    r"pagar|pago|tarjeta|nequi|pse|"
    r"link\s*de\s*pago|enlace\s*de\s*pago|"
    r"cotizar|cotización|cotizacion|cotice|"
    r"env[ií]ar|env[ií]o|despacho|"
    r"direcci[oó]n|domicilio|"
    r"c[eé]dula|documento|nit|"
    r"correo|email|"
    r"resumen|"
    r"confirmar|confirmo|confirmas?|"
    r"acepto|acepta|autorizo|autorizas?"
    r")\b",
    re.IGNORECASE,
)

# Tokens explícitamente "simple" — preguntas FAQ / informativas que NO
# requieren extracción estructurada. Si solo aparecen estos, lite alcanza.
_SIMPLE_INFO_TOKENS_RE = re.compile(
    r"\b("
    r"hola|buenos\s+d[ií]as|buenas\s+(?:tardes|noches)|saludos|"
    r"qu[eé]\s+(?:vendes|venden|tienes|tienen)|"
    r"qu[eé]\s+(?:productos?|referencias?)|"
    r"informaci[oó]n|info|"
    r"horario|atenci[oó]n|"
    r"pol[ií]tica|pol[ií]ticas|"
    r"devoluci[oó]n|devoluciones|"
    r"garant[ií]a|garant[ií]as|"
    r"c[oó]mo\s+(?:se\s+)?usa|c[oó]mo\s+conservar|"
    r"qu[eé]\s+es|de\s+qu[eé]\s+est[aá]"
    r")\b",
    re.IGNORECASE,
)


# ─── Tipos de intent ─────────────────────────────────────────────────────────

INTENT_SIMPLE = "simple"
INTENT_TRANSACTIONAL = "transactional"


# ─── Configuración de modelos ────────────────────────────────────────────────

import os


def _cfg(key: str, default: str) -> str:
    return os.getenv(key, default) or default


def _models_simple() -> tuple[str, str]:
    """Para intent simple: lite primario, flash fallback."""
    primary = _cfg("GEMINI_SIMPLE_MODEL", _cfg("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite"))
    fallback = _cfg("GEMINI_MODEL", "gemini-3.5-flash")
    return primary, fallback


def _models_transactional() -> tuple[str, str]:
    """Para intent transactional: flash primario, lite fallback."""
    primary = _cfg("GEMINI_MODEL", "gemini-3.5-flash")
    fallback = _cfg("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
    return primary, fallback


# ─── Clasificador ────────────────────────────────────────────────────────────

def classify_intent(
    query: str,
    fsm_state: Optional[str] = None,
    history: Optional[list[dict]] = None,
) -> str:
    """Clasifica el turno actual como `simple` o `transactional`.

    Reglas (en orden):
      1. Si fsm_state es transaccional (NEEDS_X, READY_FOR_SUMMARY,
         AWAITING_ORDER_CONFIRMATION) → transactional. Estamos capturando
         datos críticos, no podemos fallar.
      2. Si query contiene tokens transaccionales (comprar, pagar, link,
         cotizar, etc.) → transactional.
      3. Si history reciente menciona flujo transaccional (cliente puso
         intent en turno anterior) → transactional.
      4. Por defecto → simple (lite es suficiente).

    Esto es un default de conservadurismo: ante duda, transactional.
    Nunca degradamos calidad en duda — el costo extra es marginal.
    """
    # 1. FSM state
    if fsm_state and fsm_state in TRANSACTIONAL_FSM_STATES:
        return INTENT_TRANSACTIONAL

    q = query or ""

    # 2. Keywords transaccionales en query
    if _TRANSACTIONAL_TOKENS_RE.search(q):
        return INTENT_TRANSACTIONAL

    # 3. History reciente (últimos 3 turnos del cliente)
    if history:
        recent_inbound = [
            str(m.get("content") or "")
            for m in history[-6:]
            if str(m.get("direction") or "").lower() == "inbound"
        ][-3:]
        for prev in recent_inbound:
            if _TRANSACTIONAL_TOKENS_RE.search(prev):
                return INTENT_TRANSACTIONAL

    # 4. Default — simple
    return INTENT_SIMPLE


def model_pair_for(intent: str) -> tuple[str, str]:
    """Devuelve (primary_model, fallback_model) según intent."""
    if intent == INTENT_TRANSACTIONAL:
        return _models_transactional()
    return _models_simple()
