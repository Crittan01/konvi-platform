"""Base de invariants — Protocol + apply_invariants pipeline.

ADR-0018. Cada invariant es un guardrail Python que valida el output
candidato del LLM (post-tool-calls) contra el estado real. Si el LLM
miente o afirma algo que no pasó, el invariant lo bloquea o reescribe.

Diseño:
  • `Invariant` Protocol: implementaciones en `agentic/invariants/*.py`.
  • `apply_invariants(text, ctx, results)` — corre la lista en orden;
    primer REWRITE/BLOCK gana.
  • OK → text se preserva tal cual.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


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
) -> InvariantResult:
    """Pipeline de invariants. Corre en orden; primer REWRITE/BLOCK gana.

    Si NINGÚN invariant interviene → outcome=OK con candidate_text intacto.
    """
    for inv in invariants:
        try:
            result = await inv.validate(
                candidate_text=candidate_text,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                supabase=supabase,
                tool_call_log=tool_call_log,
            )
        except Exception as exc:
            # Invariant roto NO bloquea outbound (degradación graceful).
            # Pero loggeamos para diagnóstico.
            import logging
            logging.getLogger(__name__).warning(
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
