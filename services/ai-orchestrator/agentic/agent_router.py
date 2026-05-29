"""Router pre-LLM — clasifica inbound y elige el agente (rev. 109 ADR-0017).

Cuando un tenant tiene >1 agente activo, este router decide qué agente
atiende cada mensaje. Heurística por keywords (cero costo LLM, cero
latencia). Si el tenant tiene 1 agente → backward-compat (default).

Ejemplo:
    Cliente: "¿dónde está mi pedido #ABC12345?"
    → match keywords "dónde está" / "tracking" → role=support
    → router elige el agente con role='support' del tenant
    → Si tenant no tiene Support agent → fallback al default

Si en el futuro vemos miss-classification > 10% en métricas, escalamos
a clasificación con LLM Flash Lite (~$0.0001/turno). Hoy: heurística.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("orchestrator.agent_router")


# ─── Patterns por rol (ordenados de más específico a más general) ──────────


_CLAIMS_PATTERNS = (
    # Prefix-friendly (reclam → reclamar, reclamo; defectuos → defectuoso/a)
    re.compile(r"\breclam\w*", re.I),
    re.compile(r"\bdefectuos\w*", re.I),
    re.compile(r"\bdañ\w+", re.I),
    re.compile(r"\brot[oa]\b", re.I),
    re.compile(r"\bretract\w*", re.I),
    re.compile(r"\bdevoluci[oó]n", re.I),
    re.compile(r"\bdevolver", re.I),
    re.compile(r"\bgarant[ií]a", re.I),
    re.compile(r"\breembolso|refund", re.I),
    re.compile(r"\bno\s+funciona", re.I),
    re.compile(r"\bvino\s+mal|llegó\s+mal", re.I),
    re.compile(r"\bno\s+(?:me\s+)?(?:llegó|lleg[oó]|recib[ií])", re.I),
)

_SUPPORT_PATTERNS = (
    re.compile(r"\b(?:tracking|rastreo|seguimiento)\b", re.I),
    re.compile(r"\b(?:d[oó]nde\s+est[aá]|donde\s+esta)\s+(?:mi\s+)?pedido", re.I),
    re.compile(r"\b(?:cu[aá]ndo\s+(?:me\s+)?lleg|cuando\s+llega)", re.I),
    re.compile(r"\b(?:n[uú]mero\s+de\s+(?:gu[ií]a|env[ií]o|tracking))\b", re.I),
    re.compile(r"\b(?:est(?:atus|ado)\s+de(?:l)?\s+(?:mi\s+)?pedido)\b", re.I),
)

_MARKETING_PATTERNS = (
    re.compile(r"\b(?:promo(?:ci[oó]n)?|descuento|oferta)\b", re.I),
    re.compile(r"\b(?:cup[oó]n\s+(?:disponible|nuevo))\b", re.I),
    re.compile(r"\b(?:black\s+friday|cyber\s+monday|liquidaci[oó]n)\b", re.I),
)


# ─── Public API ─────────────────────────────────────────────────────────────


def classify_intent_to_role(text: str) -> str:
    """Clasifica el inbound por heurística keyword → rol.

    Returns: 'sales' (default) | 'support' | 'claims' | 'marketing'.

    NO usa LLM. Cero costo, cero latencia. Si en métricas vemos baja
    precisión, evolucionamos a Flash Lite ($0.0001/turno).
    """
    if not text or not isinstance(text, str):
        return "sales"

    # Orden importa — claims más específico que support
    # ("no me llegó" puede confundirse con tracking pero implica reclamo).
    if any(p.search(text) for p in _CLAIMS_PATTERNS):
        return "claims"
    if any(p.search(text) for p in _SUPPORT_PATTERNS):
        return "support"
    if any(p.search(text) for p in _MARKETING_PATTERNS):
        return "marketing"
    return "sales"


def select_agent_for_inbound(
    *,
    inbound_text: str,
    agents: list[dict],
) -> dict:
    """Selecciona el agente apropiado para el inbound dado.

    Args:
        inbound_text: contenido del mensaje del cliente.
        agents: lista de agentes activos del tenant (de
            `lib.tenant_agents.list_tenant_agents`).

    Returns:
        El agente elegido (dict). Si tenant tiene 1 solo agente o si no
        hay match específico para el rol detectado → retorna el agente
        con is_default=True. Si no hay default, el primero de la lista.
    """
    if not agents:
        # Edge case: no debería pasar (siempre hay al menos 1 default),
        # pero por defensa retornamos un dict mínimo.
        return {"name": "Sara Camila", "role": "sales", "is_default": True}

    # Backward-compat: 1 agente → siempre ese.
    if len(agents) == 1:
        return agents[0]

    classified_role = classify_intent_to_role(inbound_text)

    # Buscar agente con el rol clasificado.
    for ag in agents:
        if (ag.get("role") or "").lower() == classified_role:
            logger.info(
                "[ROUTER] inbound classified role=%s → agent=%s",
                classified_role, ag.get("name") or "?",
            )
            return ag

    # Fallback: agente default del tenant.
    for ag in agents:
        if ag.get("is_default"):
            logger.info(
                "[ROUTER] no agent for role=%s → fallback default agent=%s",
                classified_role, ag.get("name") or "?",
            )
            return ag

    # Sin default → primer agente.
    logger.warning(
        "[ROUTER] no default agent — using first of %d agents", len(agents),
    )
    return agents[0]
