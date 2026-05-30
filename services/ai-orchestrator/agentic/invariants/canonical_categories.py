"""Invariant: normaliza nombres de categorías al literal canónico.

Rev. 109 UAT live 2026-05-27 — el LLM Gemini agrega descriptores a las
categorías canónicas del prompt:
  • "Sérums" → "Sérums Faciales" (agrega "Faciales")
  • "Kits" → "Kits de Cuidado" (agrega "de Cuidado")
  • "Aceites Vegetales" → "Aceites" (omite "Vegetales", ambiguo)
  • "Aceites Esenciales" → "Aceites" (omite "Esenciales", ambiguo)

Founder UX feedback: "Solo 'Aceites' es ambiguo — debe decir Vegetales o
Esenciales". Las categorías SON el contrato de naming del tenant; el
LLM no debe inventar variaciones.

Diseño:
  • Aplica SOLO cuando el outbound presenta el bloque de categorías
    (regex anchor: presencia de ≥3 bullets con nombres tipo "Aceites" /
    "Jabones" / "Sérums" / "Kits").
  • NO aplica si el bullet es de un PRODUCTO específico (e.g. "Sérum de
    Vitamina C" — solo categorías plural).
  • Sustituye texto literal con regex word-boundary.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import InvariantOutcome, InvariantResult


# Reemplazos canónicos: (regex_pattern_que_matchea_variacion, literal_correcto).
# El orden importa: el más específico va primero (Aceites Vegetales antes que
# Aceites a secas).
_CATEGORY_REPLACEMENTS = [
    # Sérums sin/con descriptor faccial → "Sérums" literal.
    (re.compile(r"\bs[eé]rums?\s+faciales?\b", re.IGNORECASE), "Sérums"),
    # Kits sin/con "de cuidado" / "de productos" → "Kits" literal.
    (re.compile(r"\bkits?\s+de\s+cuidado\b", re.IGNORECASE), "Kits"),
    (re.compile(r"\bkits?\s+de\s+productos\b", re.IGNORECASE), "Kits"),
    # "Aceites" sin "Vegetales/Esenciales" → ambiguo. NO sustituimos
    # automáticamente porque depende del contexto del bullet (qué
    # subcategoría es). En su lugar, marcamos para REWRITE si encontramos
    # el patrón "* *Aceites*:" (categoría sola).
]

# Pattern para detectar bullets de CATEGORÍAS (no de productos):
# inicio de línea + bullet + texto en negrita corto típico de categoría.
_CATEGORY_BULLET_PATTERN = re.compile(
    r"^[\*\-]\s+\*[^*]{3,40}\*[\s:]+",
    re.MULTILINE,
)


def _is_category_listing(text: str) -> bool:
    """Heurística: el outbound presenta el bloque de categorías."""
    if not text:
        return False
    bullets = _CATEGORY_BULLET_PATTERN.findall(text)
    if len(bullets) < 3:
        return False
    # Confirma palabras-clave de categoría plural.
    plural_words = ("aceites", "jabones", "sérums", "serums", "kits", "categorías")
    text_lower = text.lower()
    return any(w in text_lower for w in plural_words)


def _normalize_categories(text: str) -> tuple[str, list[str]]:
    """Aplica reemplazos canónicos. Retorna (texto_nuevo, lista_cambios)."""
    changes: list[str] = []
    out = text
    for pat, replacement in _CATEGORY_REPLACEMENTS:
        m = pat.search(out)
        if m:
            old = m.group(0)
            out = pat.sub(replacement, out)
            changes.append(f"{old} → {replacement}")
    return out, changes


class CanonicalCategoriesInvariant:
    """Normaliza variaciones del LLM a las categorías canónicas literales.

    Solo aplica cuando outbound presenta el bloque de categorías.
    Si el outbound NO tiene formato de listado de categorías (e.g., bot
    está cotizando envío o pidiendo PII), retorna OK sin tocar nada.
    """

    name = "canonical_categories"

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

        if not _is_category_listing(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="no category listing detected",
            )

        normalized, changes = _normalize_categories(candidate_text)
        if not changes:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="categories already canonical",
            )

        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=normalized,
            reason=f"normalized: {', '.join(changes)}",
        )
