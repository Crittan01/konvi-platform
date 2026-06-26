"""Invariant: el bot NUNCA expone su mecánica interna al cliente.

Bug runtime KAIU 2026-06-26 (UAT founder, conv 56a0d757):
  Cliente: "¿Para qué sirven el aceite de árbol de té y el de lavanda?"
  Bot:     "...la BASE DE CONOCIMIENTO no me da detalles específicos de sus
            beneficios, pero te puedo asegurar que..."
  Problema: anti-alucinación (no inventar) ≠ narrar tus tripas. Un producto
            maduro NUNCA le dice al cliente "mi base de conocimiento / mi
            sistema / mi catálogo no tiene eso". Expone la implementación y se
            ve poco profesional.

Defensa en profundidad post-LLM. Las reglas de prompt (FIX B) reducen la
probabilidad, pero el LLM es no-determinístico. Este invariant GARANTIZA que
la frase nunca llegue al cliente: si aparece, REESCRIBE quitando la frase
expositora y mantiene momentum (no promete humano → evita colisión con
FakeEscalationInvariant).

ADR-0024: criterio binario/determinístico (regex sobre frases fijas que NOMBRAN
el mecanismo interno), NO parser NLP semántico.

NO bloquea — REWRITE.
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

# Frases que NOMBRAN la mecánica interna como fuente/limitación ante el cliente.
# Binario: cualquiera de estas en un outbound = exposición de internals.
_EXPOSURE_PATTERNS = (
    # "base de conocimiento" / "base de datos" — el cliente nunca debe oír esto.
    re.compile(r"\bbase\s+de\s+(?:conocimiento|datos)\b", re.IGNORECASE),
    # "mi sistema/catálogo/base (no) tiene/da/incluye/registra..."
    re.compile(
        r"\b(?:mi|el|la)\s+(?:sistema|cat[aá]logo|base)\b[^.!?\n]{0,45}\bno\s+"
        r"(?:tiene|da|incluye|me\s+da|cuenta\s+con|registra|contiene)\b",
        re.IGNORECASE,
    ),
    # "no tengo/dispongo ... en mi sistema/base / registrado en el sistema"
    re.compile(
        r"\bno\s+(?:tengo|dispongo\s+de|cuento\s+con)\b[^.!?\n]{0,45}"
        r"\b(?:en\s+mi\s+(?:sistema|base|cat[aá]logo)|registrad[oa]\s+en)\b",
        re.IGNORECASE,
    ),
)

_GRACEFUL_CLOSER = "¿Te gustaría saber más de alguno o añadirlo a tu pedido?"


def _has_exposure(text: str) -> bool:
    return any(p.search(text) for p in _EXPOSURE_PATTERNS)


def _strip_exposure(text: str) -> str:
    """Quita las oraciones que exponen internals, conserva el resto coherente."""
    # Segmentar por oración (fin de oración) y por salto de línea (preserva
    # bullets/párrafos). Mantiene las que NO exponen.
    segments = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = [s.strip() for s in segments if s.strip() and not _has_exposure(s)]
    result = " ".join(kept).strip()
    # Si quedó vacío o demasiado corto (toda la respuesta era exposición),
    # cae a un cierre grácil que mantiene la venta.
    if len(result) < 15:
        return _GRACEFUL_CLOSER
    # Asegura un cierre que destrabe el siguiente turno si no hay pregunta.
    if not re.search(r"[¿?]", result):
        result = f"{result} {_GRACEFUL_CLOSER}"
    return result


class NoInternalsExposureInvariant:
    """REWRITE si el outbound nombra la mecánica interna (KB/sistema/catálogo)
    como fuente o limitación ante el cliente."""

    name = "no_internals_exposure"

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
        if not candidate_text or not _has_exposure(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        replacement = _strip_exposure(candidate_text)
        logger.warning(
            "[INVARIANT] no_internals_exposure REWRITE conv=%s — el bot iba a "
            "exponer mecánica interna al cliente.",
            conversation_id[:8] if conversation_id else "?",
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason="outbound exponía la mecánica interna (KB/sistema/catálogo)",
        )
