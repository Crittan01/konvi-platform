"""B-1 — Routing de modelo por estado FSM (lite en exploración → flash en
transaccional), tras flag de canary.

Auditoría bot 2026-08-21 (§3): "mismo modelo lite para 'hola' y para el
checkout" (`llm_router.py` legacy era código muerto con estados de la FSM V1
— NO se reutiliza). La calidad del modelo importa más en los pasos
transaccionales (carrito/datos/envío/pago: tool-calling delicado y verdad de
dinero) que en la exploración casual.

Diseño:
  • Flag `AGENTIC_STATE_ROUTING_ENABLED` (default false) — canary STG antes
    de cualquier default (mismo patrón que AGENTIC_TOOL_VALIDATED_ENABLED).
  • Con el flag OFF, `model_for_state` devuelve (None, None) → el turno corre
    EXACTAMENTE como hoy (AGENTIC_MODEL + fallback default).
  • Con el flag ON: estados pre-cart (GREETING/EXPLORING) siguen en lite;
    el resto (CART_BUILDING y todo el checkout) corre con
    `AGENTIC_MODEL_TRANSACTIONAL` (default gemini-3.5-flash) como primario y
    AGENTIC_MODEL (lite) como fallback — el fallback NUNCA es el modelo más
    caro que el primario en su tier (la inversión de 2026-07-07 documentada
    en llm_invoke.py).
  • `AgenticState.is_pre_cart` / `is_checkout` ya existen (states.py) — el
    mapeo es trivial y data-driven.

Costo consciente (precios Track 6): 3.5-flash = $1.50/$9.00 vs lite
$0.25/$1.50 por 1M tokens (6×). El routing solo sube los turnos
transaccionales; la medición del canary vive en agentic_shadow_log
(model_used por turno, migración 20260822130500).
"""
from __future__ import annotations

import os
from typing import Optional

# Estados que se consideran transaccionales para el routing: todo lo que no
# es pre-cart (GREETING/EXPLORING). CART_BUILDING va como transaccional —
# tool-calling de carrito frecuente (add/remove) con verdad de dinero.
_TRANSACTIONAL_DEFAULT = "gemini-3.5-flash"


def state_routing_enabled() -> bool:
    """Flag de canary (leído fresco por llamada — flip sin redeploy)."""
    return os.getenv("AGENTIC_STATE_ROUTING_ENABLED", "false").lower() in {
        "1", "true", "yes", "on",
    }


def model_for_state(state) -> tuple[Optional[str], Optional[str]]:
    """(primary, fallback) para el estado FSM del turno.

    Devuelve (None, None) → el turno usa los defaults de siempre
    (AGENTIC_MODEL + fallback de llm_invoke). Cualquier duda (flag off,
    estado desconocido) → (None, None): el comportamiento actual nunca cambia
    por accidente.
    """
    if not state_routing_enabled() or state is None:
        return None, None

    is_pre_cart = bool(getattr(state, "is_pre_cart", False))
    if is_pre_cart:
        return None, None  # exploración: lite default (barato y suficiente)

    primary = os.getenv("AGENTIC_MODEL_TRANSACTIONAL", _TRANSACTIONAL_DEFAULT)
    # Fallback del tier transaccional: el modelo LITE del path (nunca uno más
    # caro que el primario — ver nota de inversión en el docstring).
    fallback = os.getenv("AGENTIC_MODEL", "gemini-3.1-flash-lite")
    return primary, fallback
