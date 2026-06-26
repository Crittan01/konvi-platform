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


_HANDOFF_SYNTHETIC_AGENT = {
    "name": "Asistente",
    "role": "handoff",
    "role_description": (
        "Tu ÚNICA función ahora es transmitirle al cliente con calidez "
        "que su consulta se enviará a un asesor humano que le responderá "
        "lo antes posible. NO uses ninguna tool. NO ofrezcas productos. "
        "NO respondas sobre catálogo, envíos, precios ni nada operativo. "
        "Responde en máximo 2 líneas en español Colombia, cordial y "
        "profesional. Ejemplo: 'Recibido. En breve te contacta uno de "
        "nuestros asesores para resolver tu consulta.'"
    ),
    "tools_allowed": [],
    "fsm_states_allowed": None,
    "is_default": False,
    "_needs_human_handoff": True,
}


def select_agent_for_inbound(
    *,
    inbound_text: str,
    agents: list[dict],
) -> dict:
    """Selecciona el agente apropiado para el inbound dado.

    Rev. 109 fallback_for_roles explícito (founder 2026-05-28):
    cuando el role clasificado NO matchea especialista, ANTES de caer al
    default verifica que el role esté en `default.fallback_for_roles`.
    Si NO está → retorna agente sintético de handoff humano (el dispatcher
    ya pasa role_description al system prompt, así que esta respuesta cae
    naturalmente).

    Backward-compat: agentes default seedeados con los 4 roles → NUNCA
    se activa handoff. Operador desmarca explícitamente para activarlo.

    Args:
        inbound_text: contenido del mensaje del cliente.
        agents: lista de agentes activos del tenant.

    Returns:
        Dict del agente. Si activa handoff humano, dict incluye
        `_needs_human_handoff=True` para que upstream alerte operador
        (cuando esté implementado el canal de notificación).
    """
    if not agents:
        return {"name": "Sara Camila", "role": "sales", "is_default": True}

    if len(agents) == 1:
        return agents[0]

    classified_role = classify_intent_to_role(inbound_text)

    for ag in agents:
        if (ag.get("role") or "").lower() == classified_role:
            logger.info(
                "[ROUTER] inbound classified role=%s → agent=%s",
                classified_role, ag.get("name") or "?",
            )
            return ag

    # No especialista. Antes de caer al default, verificar fallback explícito.
    default_agent = next(
        (ag for ag in agents if ag.get("is_default")), None,
    )

    if default_agent is not None:
        fallback_roles = default_agent.get("fallback_for_roles")
        # Tolerante a None (DB row pre-migration) → backward-compat 100%
        # tratando como "cubre los 4 roles" (comportamiento previo).
        if fallback_roles is None or classified_role in fallback_roles:
            logger.info(
                "[ROUTER] no agent for role=%s → fallback default agent=%s "
                "(fallback_for_roles=%s)",
                classified_role, default_agent.get("name") or "?",
                fallback_roles,
            )
            return default_agent
        # Role NO está en fallback explícito del default → handoff humano.
        logger.info(
            "[ROUTER] role=%s NO está en default.fallback_for_roles=%s → "
            "handoff humano",
            classified_role, fallback_roles,
        )
        return dict(_HANDOFF_SYNTHETIC_AGENT)

    logger.warning(
        "[ROUTER] no default agent — using first of %d agents", len(agents),
    )
    return agents[0]
