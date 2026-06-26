"""Invariant: consent Habeas Data requerido antes de save_pii.

ADR-0018 + ADR-0003 (Habeas Data Ley 1581 CO).

Production-grade: defensa en profundidad. El tool `save_pii` ya verifica
consent internamente y falla si no hay. Este invariant chequea que el
LLM no afirme haber guardado PII si save_pii falló por falta de consent.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


_PII_AFFIRMATIVE_PATTERNS = (
    re.compile(r"\b(?:guarde|guard[eé]|registre|registr[eé])\b", re.IGNORECASE),
    re.compile(r"\b(?:tengo\s+tus|anote|anot[eé])\s+datos\b", re.IGNORECASE),
)


def _llm_affirms_pii_saved(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _PII_AFFIRMATIVE_PATTERNS)


_SAVE_TOOLS = {
    "save_email", "save_name", "save_document",
    "save_address", "save_shipping_phone",
}


def _save_pii_failed_by_consent(tool_call_log: list[dict]) -> bool:
    """True si en este turn algún save_* falló con code='CONSENT_REQUIRED'."""
    for call in tool_call_log:
        if call.get("tool") not in _SAVE_TOOLS:
            continue
        result = call.get("result") or {}
        if result.get("code") == "CONSENT_REQUIRED":
            return True
    return False


class ConsentRequiredInvariant:
    """Si save_pii falló por falta de consent, el LLM no debe afirmar
    haber guardado datos del cliente."""

    name = "consent_required"

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
        if not _llm_affirms_pii_saved(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        if not _save_pii_failed_by_consent(tool_call_log):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        # LLM afirma guardado PII PERO save_pii falló por consent.
        replacement = (
            "Antes de tomar tus datos necesito tu autorización para tratarlos "
            "(Habeas Data). ¿Estás de acuerdo? Responde *SÍ* o *NO*."
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason="LLM afirmó PII saved pero save_pii bloqueó por falta de consent",
        )
