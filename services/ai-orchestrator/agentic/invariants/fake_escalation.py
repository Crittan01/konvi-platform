"""Invariant: detecta "fake escalation" — bot promete especialista/equipo
SIN haber invocado `escalate_to_human`. Bug runtime founder 2026-05-28
(super delicado): si el cliente recibe "te paso con un especialista" y
la conv NO se marca como human_takeover, NADIE es notificado → cliente
colgado indefinidamente.

Pattern observado en UAT live multi-agente KAIU:
  Cliente: "Necesito reclamo urgente, llegó dañado, exijo garantía"
  Bot (Carolina/claims): "Lo mejor es que un especialista te ayude..."
  Real:   tool_call_log=[] → status='bot_active' → 0 notificaciones.

Causa raíz: agentes especialistas (con role_description custom de IA)
generan texto cordial de escalado pero NO incluye instrucción técnica de
LLAMAR `escalate_to_human`. El LLM "actúa" la escalación lingüísticamente
sin ejecutar el side-effect.

DEFENSA EN PROFUNDIDAD:
  • Si candidate_text contiene frase de escalación + tool_call_log NO
    incluye escalate_to_human → ejecutar el escalado REAL aquí:
      1. UPDATE conversations.status='human_takeover'.
      2. INSERT messages (escalation_audit) con reason.
      3. Notificar Telegram (best-effort via notify_escalation_async).
  • El candidate_text se MANTIENE (la promesa al cliente es válida AHORA
    que el side-effect ocurrió). No reescribimos — solo "respaldamos"
    con la acción real.

Resultado: si el LLM dice "te paso con un especialista", el cliente
SIEMPRE recibirá atención humana. Sin fake escalation jamás.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)

logger = logging.getLogger(__name__)


# Patrones de "te conecto/paso/escalo con especialista/equipo/asesor".
# Cubre variantes naturales del LLM cuando un agente decide handoff
# pero olvida invocar el tool. Diseño: matches específicos, evita
# falsos positivos en frases inocentes ("nuestro especialista en
# cosmética te puede informar..." → NO es escalation, es info).
_ESCALATION_PROMISE_PATTERNS = (
    # "te paso/conecto/derivo con un/mi/nuestro especialista/asesor/equipo"
    re.compile(
        r"\b(?:te|le)\s+(?:paso|conecto|derivo|transfiero|comunico)\s+"
        r"(?:con|a)\s+(?:un[a]?|mi|el|la|nuestr[oa]|tu)?\s*"
        r"(?:especialista|asesor|agente|equipo|operador|encargad[oa])\b",
        re.IGNORECASE,
    ),
    # "voy a escalar / escalo / escalaré / debo escalar tu caso/situación"
    re.compile(
        r"\b(?:voy\s+a\s+escalar|escal[aoé]r?|debo\s+escalar)\b",
        re.IGNORECASE,
    ),
    # "lo mejor es que un especialista te ayude/atienda/contacte"
    re.compile(
        r"\b(?:lo\s+mejor\s+es\s+que|necesito\s+que|requiere\s+que)\s+"
        r"(?:un[a]?\s+)?(?:especialista|asesor|agente|operador|"
        r"persona\s+(?:de\s+)?mi\s+equipo)\b",
        re.IGNORECASE,
    ),
    # "mi equipo / nuestro equipo se contactar(á|í) / te llamar(á|í)"
    re.compile(
        r"\b(?:mi|nuestro|el)\s+equipo\s+(?:se|te)\s+(?:contactar|llamar|comunicar|atender)",
        re.IGNORECASE,
    ),
    # "te contactará un especialista / asesor"
    re.compile(
        r"\b(?:te|le)\s+(?:contactar|llamar|atender)[áa]?\s+"
        r"(?:un[a]?\s+)?(?:especialista|asesor|agente|operador)",
        re.IGNORECASE,
    ),
)


def detects_escalation_promise(text: str) -> bool:
    """True si el outbound promete handoff humano explícito."""
    if not text or not isinstance(text, str):
        return False
    return any(p.search(text) for p in _ESCALATION_PROMISE_PATTERNS)


def _executed_escalate_tool(tool_call_log: list[dict]) -> bool:
    """True si escalate_to_human fue invocado en este turn."""
    for call in tool_call_log or []:
        tool_name = (call.get("tool") or "").strip()
        if tool_name == "escalate_to_human":
            success = call.get("success")
            # Si success=False, el escalado fracasó pero el LLM ya intentó.
            # Igual lo consideramos "invocado" — no es fake.
            return True
    return False


class FakeEscalationInvariant:
    """Garantiza que la promesa de escalación tenga side-effect real."""

    name = "fake_escalation"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
    ) -> InvariantResult:
        if not detects_escalation_promise(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="no escalation phrase detected",
            )

        if _executed_escalate_tool(tool_call_log):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="escalate_to_human tool was invoked",
            )

        # Fake escalation detectada — ejecutar el side-effect REAL ahora.
        # Defense in depth: el cliente recibió la promesa; debemos
        # cumplirla aunque el LLM olvidó invocar la tool.
        reason_text = (
            "Fake escalation auto-corregida — LLM prometió especialista "
            "sin invocar escalate_to_human. Invariant FakeEscalation forzó "
            "el side-effect para garantizar atención humana."
        )
        logger.warning(
            "[INVARIANT.FAKE_ESCALATION] conv=%s: promesa sin tool — "
            "forzando escalado real",
            conversation_id[:8] if conversation_id else "?",
        )

        # 1. Cambiar status conv → human_takeover.
        try:
            supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            logger.error(
                "[INVARIANT.FAKE_ESCALATION] error actualizando status conv=%s: %s",
                conversation_id, exc,
            )
            # Si falla el status update, NO podemos garantizar atención
            # humana. BLOCK el outbound para no mentir al cliente —
            # mejor que el cliente reciba mensaje neutro que promesa rota.
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=(
                    "Permíteme verificar y te respondo enseguida con la "
                    "mejor opción para tu caso."
                ),
                reason=f"status update failed: {exc}",
            )

        # 2. Audit append-only en messages (escalation_audit).
        try:
            supabase.table("messages").insert({
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "content_type": "escalation_audit",
                "content": "",
                "payload": {
                    "reason": reason_text,
                    "source": "invariant_fake_escalation",
                    "candidate_text_preview": candidate_text[:200],
                },
                "processed": True,
                "processing_status": "processed",
            }).execute()
        except Exception:
            # Audit log NO bloquea — status ya está cambiado.
            pass

        # 3. Notificar Telegram (best-effort).
        try:
            from telegram_notifications import notify_escalation_async
            await notify_escalation_async(
                supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                reason=reason_text,
            )
        except Exception:
            # Path A puede fallar — Path B (DB trigger → pgmq → worker)
            # respaldará via notification_settings.
            pass

        # El candidate_text se preserva — ahora es ARRESPALDADO por el
        # side-effect real. El cliente recibe lo prometido.
        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason=(
                "fake escalation detectada → side-effect ejecutado "
                "(status=human_takeover + audit + telegram). "
                "Candidate preservado."
            ),
        )
