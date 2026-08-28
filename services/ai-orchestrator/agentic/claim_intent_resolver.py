"""Detección de contexto de RECLAMO — B-2 (H11, 2026-08-28).

H11 (harness B-3 2026-08-24, xfail `t8_reclamo_coherente` + conversación real
del founder en PRD 2026-08-28): un reclamo sin pedido identificable derivaba al
flujo de compra — el LLM pedía PII para "registrar" el caso → el embudo
reescribía al consent con framing de COMPRA ("Voy a continuar con tu pedido…
¿Estás de acuerdo? *SÍ* o *NO*") → loop.

Diseño (decisión founder 2026-08-28 — "el bot lleva la conversación en base a
lo que el cliente vaya expresando, más humano"): la VOZ la compone el LLM con
el contexto del turno; lo determinístico es la DETECCIÓN de la situación y la
garantía de la acción (la escalación real la fuerza `FakeEscalationInvariant` si
el LLM promete sin invocar el tool). Este módulo NO produce texto al cliente —
solo detecta contexto para:

  • `outbound/validator.py` (vía `orchestrator._send_outbound_text`): elegir el
    framing del consent — en contexto de reclamo se usa
    `CONSENT_QUESTION_TEMPLATE_CLAIM` (misma acción legal Ley 1581, framing
    on-topic), nunca el de compra.

Migración B-2: esta detección es la semilla del futuro state handler CLAIMS
(docs/architecture/bot-dispatcher-reengineering.md §2-3).
"""
from __future__ import annotations

from typing import Any

from agentic.agent_router import classify_intent_to_role


def detect_claim_intent(inbound_text: str) -> bool:
    """True si el inbound es un reclamo.

    Fuente única de la clasificación: `agent_router.classify_intent_to_role`
    (vocabulario `_CLAIMS_PATTERNS` — reclam*/defectuos*/dañ*/roto/retracto/
    devolución/garantía/reembolso/no-funciona/no-llegó…). Cero divergencia:
    el mismo criterio que el router multi-agente.
    """
    if not inbound_text:
        return False
    return classify_intent_to_role(inbound_text) == "claims"


def is_claim_context(history: Any, *, lookback_inbounds: int = 3) -> bool:
    """True si los inbounds recientes del history son un reclamo.

    Lo consume el embudo al elegir el framing del consent: si la conversación
    activa es un reclamo, la pregunta de autorización (cuando aplica) debe
    hablar del RECLAMO, no de la compra.

    `history`: filas de `messages` con `direction`/`content` (orden cronológico
    o DESC — se miran los últimos N inbounds). Fail-open: ante forma rara,
    False (contexto compra — el comportamiento de siempre).
    """
    try:
        rows = [m for m in (history or []) if isinstance(m, dict)]
    except TypeError:
        return False
    inbounds = [
        str(m.get("content") or "")
        for m in rows
        if str(m.get("direction") or "").lower() == "inbound"
    ]
    for text in reversed(inbounds[-lookback_inbounds:]):
        if detect_claim_intent(text):
            return True
    return False
