"""Invariant: bot NO puede afirmar 'guardé tu email/dirección/etc.'
sin haber invocado save_contact_field para ese campo en este turn.

Rev. 109 UAT live BUG 19 — runtime founder 2026-05-28:
  Cliente da email → bot dice "He guardado tu correo electrónico" pero
  el tool save_contact_field NUNCA se invocó → DB.email = NULL.
  Cliente confía en el bot, sigue el flow, pero el dato real falta.

Mismo patrón que ConsentRequiredInvariant pero para ops PII save.

REGLAS:
  • Outbound afirma "guardé/registré/anoté/he guardado tu email/correo"
    → debe haber save_contact_field(field=email) exitoso en tool_call_log.
  • Idem para name, document, address, shipping_phone.
  • Si afirma sin tool → REWRITE a pregunta natural pidiendo reenvío.

NO aplica si:
  • Outbound NO afirma save (e.g. pregunta o saluda).
  • Tool call exitoso para ese field SÍ ocurrió.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import InvariantOutcome, InvariantResult


# Phrases que indican "bot afirma haber guardado un dato".
_SAVE_AFFIRMATION_PATTERNS = {
    "email": re.compile(
        r"\b(?:he\s+)?(?:guard(?:ad[oa]|[aée])|registr(?:ad[oa]|[aée])|anot(?:ad[oa]|[aée])|tom(?:ad[oa]|[aée])\s+nota\s+de)\s+"
        r"(?:tu\s+)?(?:correo|email|e-?mail)\b",
        re.IGNORECASE,
    ),
    "name": re.compile(
        r"\b(?:he\s+)?(?:guard(?:ad[oa]|[aée])|registr(?:ad[oa]|[aée])|anot(?:ad[oa]|[aée])|tom(?:ad[oa]|[aée])\s+nota\s+de)\s+"
        r"(?:tu\s+)?nombre\b",
        re.IGNORECASE,
    ),
    "document": re.compile(
        r"\b(?:he\s+)?(?:guard(?:ad[oa]|[aée])|registr(?:ad[oa]|[aée])|anot(?:ad[oa]|[aée])|tom(?:ad[oa]|[aée])\s+nota\s+de)\s+"
        r"(?:tu\s+)?(?:documento|c[eé]dula|cc|nit)\b",
        re.IGNORECASE,
    ),
    "address": re.compile(
        r"\b(?:he\s+)?(?:guard(?:ad[oa]|[aée])|registr(?:ad[oa]|[aée])|anot(?:ad[oa]|[aée])|tom(?:ad[oa]|[aée])\s+nota\s+de)\s+"
        r"(?:tu\s+)?(?:direcci[oó]n|domicilio)\b",
        re.IGNORECASE,
    ),
    "shipping_phone": re.compile(
        r"\b(?:he\s+)?(?:guard(?:ad[oa]|[aée])|registr(?:ad[oa]|[aée])|anot(?:ad[oa]|[aée])|tom(?:ad[oa]|[aée])\s+nota\s+de)\s+"
        r"(?:tu\s+)?"
        r"(?:n[uú]mero\s+(?:de\s+)?)?"
        r"(?:celular|tel[eé]fono|contacto)\b",
        re.IGNORECASE,
    ),
}


def _tool_saved_field(tool_call_log: list[dict], field: str) -> bool:
    """True si save_contact_field exitoso para `field` en el turn."""
    for call in tool_call_log or []:
        if call.get("tool") != "save_contact_field":
            continue
        result = call.get("result") or {}
        if "error" in result or "code" in result:
            continue
        # Tool retorna {"field": "email", "saved": True}
        if result.get("field") == field and result.get("saved"):
            return True
    return False


def _build_rewrite(field: str, outbound_text: str) -> str:
    """Mensaje natural pidiendo reenvío del dato. NO debe delatar bot."""
    labels = {
        "email": "correo electrónico",
        "name": "nombre completo",
        "document": "número de documento",
        "address": "dirección completa",
        "shipping_phone": "número de celular de contacto",
    }
    label = labels.get(field, "ese dato")
    return (
        f"Disculpa, no logré procesar tu {label}. ¿Me lo puedes reenviar "
        f"para guardarlo correctamente?"
    )


class PIISaveTruthfulnessInvariant:
    """Si bot dice 'guardé X' pero save_contact_field(field=X) no corrió,
    REWRITE a pregunta natural pidiendo reenvío.

    Prevent hallucination grave: cliente confía 'guardé email' pero
    DB queda NULL → fallback luego rompe flow.
    """

    name = "pii_save_truthfulness"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
        inbound_text: str = "",
    ) -> InvariantResult:
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        for field, pattern in _SAVE_AFFIRMATION_PATTERNS.items():
            if pattern.search(candidate_text):
                if not _tool_saved_field(tool_call_log, field):
                    return InvariantResult(
                        outcome=InvariantOutcome.REWRITE,
                        invariant_name=self.name,
                        replacement_text=_build_rewrite(field, candidate_text),
                        reason=(
                            f"bot afirmó guardar {field} pero "
                            f"save_contact_field({field}) NO exitoso"
                        ),
                    )
        return InvariantResult(
            outcome=InvariantOutcome.OK, invariant_name=self.name,
            reason="ok",
        )
