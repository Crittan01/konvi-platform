"""B-1 (F7, auditoría bot 2026-08-21) — coherencia post-escalación.

El problema: cuando la conversación queda en human_takeover EN ESTE TURNO
(tool `escalate_to_human` o side-effect real de FakeEscalation), el mensaje
que sale puede mezclar la despedida con CTA transaccional ("te paso con un
especialista Y confirma tu pago / ¿cómo prefieres pagar?"). El cliente recibe
la contradicción y, peor, si responde al CTA su mensaje se skipea en silencio
(la conv ya está en takeover → gate `_should_skip_for_conv_status`).

Decisión: si la conv quedó en human_takeover este turno y el candidate trae
CTA transaccional (link de pago, pregunta de modo de pago, total a pagar,
confirmación de pago, recotización), REWRITE a una despedida canónica limpia
— la conversación la continúa el humano. Si el candidate ya es una despedida
limpia, se preserva.

Posición en la cadena: DESPUÉS de FakeEscalation (que es quien puede ejecutar
el side-effect y corre con política "preservar candidate") y de PassiveClosing
(que no debe re-añadir CTA a una despedida de escalación). Es el último
guardrail semántico antes de los cosméticos.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from agentic.invariants.base import InvariantOutcome, InvariantResult

logger = logging.getLogger(__name__)

# CTAs transaccionales que NO deben salir en la burbuja de escalación.
_TXN_CTA_RES = (
    re.compile(r"checkout\.wompi\.co|link de pago", re.IGNORECASE),
    re.compile(r"prefieres pagar|c[oó]mo (?:quieres|prefieres) pagar", re.IGNORECASE),
    re.compile(r"total a pagar|total\s*:\s*\$", re.IGNORECASE),
    re.compile(r"confirma(?:r|me|s)?\s+(?:el\s+|tu\s+)?pago", re.IGNORECASE),
    re.compile(r"te recotizo|recalcul\w*\s+(?:el\s+)?env", re.IGNORECASE),
)

# Despedida canónica: confirma la escalación, sin CTA comercial. La conversación
# la continúa el operador humano (la promesa ya quedó respaldada por el
# side-effect real: status + audit + alerta Telegram).
_GOODBYE_CLEAN = (
    "Perfecto, ya le paso tu conversación a un especialista de nuestro "
    "equipo para que te ayude personalmente. Te escribimos por aquí mismo "
    "a la brevedad. 🙌"
)


class PostEscalationCoherenceInvariant:
    """Si la conv quedó en human_takeover este turno, el outbound debe ser
    una despedida limpia — sin CTA transaccional."""

    name = "post_escalation_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str] = None,
        supabase: Any = None,
        tool_call_log: Optional[list] = None,
        inbound_text: Optional[str] = None,
        **_: Any,
    ) -> InvariantResult:
        # Señal 1: la tool de escalación se invocó en este turno.
        escalated = any(
            str(c.get("tool") or "") == "escalate_to_human"
            for c in (tool_call_log or [])
        )
        # Señal 2: el status ya es human_takeover (side-effect de
        # FakeEscalation — el gate de skip garantiza que al INICIO del turno
        # la conv NO estaba en takeover, así que pasó en este turno).
        if not escalated:
            try:
                res = (
                    supabase.table("conversations")
                    .select("status")
                    .eq("id", conversation_id)
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
                )
                row = (getattr(res, "data", None) or [{}])[0]
                escalated = str(row.get("status") or "") == "human_takeover"
            except Exception as exc:
                # Fail-open: no rompe el turno si la lectura falla.
                logger.info(
                    "[POST_ESCALATION] status lookup falló conv=%s: %s — OK",
                    str(conversation_id)[:8], exc,
                )
                return InvariantResult(
                    outcome=InvariantOutcome.OK, invariant_name=self.name,
                )

        if not escalated:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        text = candidate_text or ""
        if not any(rx.search(text) for rx in _TXN_CTA_RES):
            # Despedida limpia — se preserva.
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        logger.warning(
            "[POST_ESCALATION] conv=%s: burbuja de escalación con CTA "
            "transaccional — reescribiendo a despedida limpia",
            str(conversation_id)[:8],
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=_GOODBYE_CLEAN,
            reason="escalación con CTA transaccional mezclado — despedida canónica",
        )
