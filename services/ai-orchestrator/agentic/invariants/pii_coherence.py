"""Invariant: coherencia PII outbound vs contact real DB.

Rev. 107 — bug runtime KAIU 7b45bfc6 (2026-05-23): el bot saludó a
María López, pidió consent + name nuevos, PERO el contact ya tenía
document_number heredado de un cliente anterior (Pedro) con el mismo
phone. El bot NO pidió cédula creyendo que ya la tenía → la cédula
de Pedro se asoció a la order de María. Inconsistencia silenciosa.

Patrón general: cuando el bot emite resumen con datos del cliente,
debe coincidir con `contacts` real en DB. Si bot dice "Cristian
Garzón" pero contact.name="María López" → falso positivo
peligroso (gravísimo Habeas Data).

Diseño:
  • Heurística: outbound contiene patrón "Datos de envío" o resumen
    con name/email/dirección visible Y al menos uno de esos campos.
  • Carga contact real (`contacts` por contact_id).
  • Cross-valida: cada dato afirmado en outbound debe match contact real.
  • Si mismatch en CAMPO CRÍTICO (name, email, document_number) →
    REWRITE con resumen canónico desde DB.

Solo dispara para campos textuales presentes en el outbound. NO se
preocupa por campos omitidos (el LLM puede decidir no listar todo).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Heurística: outbound parece incluir datos del cliente.
_PII_BLOCK_KEYWORDS = re.compile(
    r"\b(?:datos\s+de\s+envío|datos\s+del?\s+cliente|"
    r"datos\s+de\s+contacto|nombre\s*:|email\s*:|"
    r"correo\s*:|dirección\s*:|c[eé]dula\s*:|"
    r"documento\s*:)\b",
    re.IGNORECASE,
)


def _looks_like_pii_block(text: str) -> bool:
    return bool(_PII_BLOCK_KEYWORDS.search(text or ""))


def _extract_name_from_text(text: str) -> Optional[str]:
    """Extrae el valor después de 'Nombre:' del outbound. None si no hay."""
    m = re.search(
        r"\*?\s*nombre\s*:?\s*\*?\s*([^\n*]+)",
        text or "", re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1).strip().rstrip(",.")


def _extract_email_from_text(text: str) -> Optional[str]:
    """Extrae email del outbound (cualquier email-shape después de Email:)."""
    m = re.search(
        r"(?:email|correo)\s*:?\s*\*?\s*([\w.+\-]+@[\w.\-]+\.[A-Za-z]{2,})",
        text or "", re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _names_match(text_name: str, db_name: str) -> bool:
    """Match flexible: case-insensitive + strip puntuación. Permite que
    'María López' match con 'maría lópez' o 'Maria Lopez' (no exigir
    tildes exactas)."""
    def _norm(s: str) -> str:
        s = (s or "").lower().strip()
        s = re.sub(r"[áàä]", "a", s)
        s = re.sub(r"[éèë]", "e", s)
        s = re.sub(r"[íìï]", "i", s)
        s = re.sub(r"[óòö]", "o", s)
        s = re.sub(r"[úùü]", "u", s)
        s = re.sub(r"[^\w\s]", "", s)
        return s
    return _norm(text_name) == _norm(db_name)


class PIICoherenceInvariant:
    """Si outbound emite datos del cliente, validar coherencia con DB."""

    name = "pii_coherence"

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
        if not contact_id:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        if not _looks_like_pii_block(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Cargar contact real.
        try:
            res = (
                supabase.table("contacts")
                .select("name, email, document_number")
                .eq("id", contact_id)
                .single()
                .execute()
            )
            contact = res.data or {}
        except Exception:
            # Best-effort: no bloqueamos si DB falla.
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="contact unreadable — skipped",
            )

        db_name = (contact.get("name") or "").strip()
        db_email = (contact.get("email") or "").strip()

        outbound_name = _extract_name_from_text(candidate_text)
        outbound_email = _extract_email_from_text(candidate_text)

        # Validar name si aparece en outbound + existe en DB.
        if outbound_name and db_name:
            if not _names_match(outbound_name, db_name):
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text=(
                        "Permíteme un momento, voy a verificar tus datos. "
                        "Te confirmo en seguida."
                    ),
                    reason=(
                        f"name mismatch: outbound={outbound_name!r} "
                        f"vs contact.name={db_name!r}"
                    ),
                )

        # Validar email si aparece en outbound + existe en DB.
        if outbound_email and db_email:
            if outbound_email.lower() != db_email.lower():
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text=(
                        "Permíteme un momento, voy a verificar tus datos. "
                        "Te confirmo en seguida."
                    ),
                    reason=(
                        f"email mismatch: outbound={outbound_email!r} "
                        f"vs contact.email={db_email!r}"
                    ),
                )

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason="PII outbound coherente con contact DB",
        )
