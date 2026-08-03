"""Base de invariants — Protocol + apply_invariants pipeline.

ADR-0018. Cada invariant es un guardrail Python que valida el output
candidato del LLM (post-tool-calls) contra el estado real. Si el LLM
miente o afirma algo que no pasó, el invariant lo bloquea o reescribe.

Diseño:
  • `Invariant` Protocol: implementaciones en `agentic/invariants/*.py`.
  • `apply_invariants(text, ctx, results)` — corre la lista en orden;
    primer REWRITE/BLOCK gana.
  • OK → text se preserva tal cual.
  • Ante EXCEPCIÓN de un invariant: fail-open (warning + skip) para los
    cosméticos/semánticos, pero FAIL-CLOSED para los de dinero/verdad
    (`FAIL_CLOSED_INVARIANTS`): un guardrail de dinero caído NO deja pasar
    el texto sin validar — se bloquea y se sirve un mensaje neutro seguro.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from agentic.degraded_messages import DEGRADED_GENERIC

logger = logging.getLogger(__name__)

try:
    from observability import capture_exception as _capture_exception
except Exception:  # pragma: no cover - import defensivo (tests sin observability)
    def _capture_exception(exc: BaseException, **extra: Any) -> None:
        return None


# A4 (2026-08-02) — invariants de dinero/verdad que cierran fail-closed ante
# EXCEPCIÓN (no ante veredicto: un REWRITE/BLOCK normal sigue su curso). Si uno
# de estos no pudo correr (DB caída, bug), el texto del LLM pasa SIN la
# validación que protege plata/verdad transaccional → riesgo de afirmación
# falsa de pago/resumen/PII/escalación. Los demás invariants (cosméticos,
# tono, exposición) mantienen fail-open: peor caso es un outbound feo, no
# una mentira de dinero.
FAIL_CLOSED_INVARIANTS = frozenset({
    "payment_coherence",
    "summary_coherence",
    "pii_save_truthfulness",
    "fake_escalation",
})


class InvariantOutcome(str, Enum):
    OK = "ok"
    REWRITE = "rewrite"
    BLOCK = "block"


@dataclass(frozen=True)
class InvariantResult:
    outcome: InvariantOutcome
    invariant_name: str
    replacement_text: Optional[str] = None
    reason: str = ""


@runtime_checkable
class Invariant(Protocol):
    """Contrato uniforme para invariants."""

    name: str

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
        """Valida el candidate_text contra el estado real.

        Returns:
          InvariantResult con outcome OK | REWRITE | BLOCK.
        """
        ...


async def apply_invariants(
    invariants: list[Invariant],
    *,
    candidate_text: str,
    tenant_id: str,
    conversation_id: str,
    contact_id: Optional[str],
    supabase: Any,
    tool_call_log: list[dict],
    inbound_text: str = "",
) -> InvariantResult:
    """Pipeline de invariants. Corre en orden; primer REWRITE/BLOCK gana.

    Si NINGÚN invariant interviene → outcome=OK con candidate_text intacto.

    `inbound_text` (opcional, rev. 107) es el último mensaje del cliente —
    algunos invariants lo usan para componer replacements contextuales.
    """
    for inv in invariants:
        try:
            # Backward compat: solo pasamos inbound_text a los invariants
            # que lo aceptan en su signature.
            sig = inspect.signature(inv.validate)
            kwargs = dict(
                candidate_text=candidate_text,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                supabase=supabase,
                tool_call_log=tool_call_log,
            )
            if "inbound_text" in sig.parameters:
                kwargs["inbound_text"] = inbound_text
            result = await inv.validate(**kwargs)
        except Exception as exc:
            if inv.name in FAIL_CLOSED_INVARIANTS:
                # A4 — guardrail de dinero/verdad CAÍDO: el texto NO sale
                # sin validar. BLOCK + mensaje neutro seguro (el mismo
                # degraded del dispatcher). Sentry por invariant caído.
                logger.error(
                    "[AGENTIC.INVARIANT] %s raised (fail-closed — outbound "
                    "bloqueado): %s", inv.name, exc,
                )
                _capture_exception(exc, invariant=inv.name)
                return InvariantResult(
                    outcome=InvariantOutcome.BLOCK,
                    invariant_name=inv.name,
                    replacement_text=DEGRADED_GENERIC,
                    reason=f"invariant_exception_fail_closed: {exc}",
                )
            # Invariant roto NO bloquea outbound (degradación graceful).
            # Pero loggeamos para diagnóstico.
            logger.warning(
                "[AGENTIC.INVARIANT] %s raised: %s", inv.name, exc,
            )
            continue
        if result.outcome != InvariantOutcome.OK:
            return result
    return InvariantResult(
        outcome=InvariantOutcome.OK,
        invariant_name="none",
        reason="all invariants passed",
    )
