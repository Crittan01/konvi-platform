"""Invariant Python: strip emojis decorativos del outbound.

ADR-0018. Defensa en profundidad: el system_prompt prohíbe emojis, pero
si el LLM los inserta igualmente, este invariant los remueve.

Excepción: 📋 (marcador estructural del resumen de pedido) se preserva.

Diseño:
  • Outcome=REWRITE si encuentra emojis fuera del set whitelisted.
  • NO bloquea — solo limpia el texto.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Whitelist de emojis estructurales (preservar). Sincronizado con
# system_prompt sección ESTILO — rev. 107 founder feedback de formato
# WhatsApp más rico (faq.whatsapp.com/539178204879377):
#   • 📋 = marcador inicio del *Resumen* de pedido.
#   • 🚚 = marcador *Envío* o *Seguimiento*.
#   • ✅ = marcador *Pago confirmado* (post-Wompi APPROVED).
_ALLOWED_EMOJIS = {"📋", "🚚", "✅", "💵"}

# Rango Unicode amplio de emojis decorativos.
# Cubre: emoticons (1F600-1F64F), symbols (2600-27BF, 2B00-2BFF),
# transport (1F680-1F6FF), miscellaneous (1F300-1F5FF, 1F900-1F9FF, etc.).
_EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"    # symbols & pictographs
    "\U0001F680-\U0001F6FF"    # transport & map
    "\U0001F900-\U0001F9FF"    # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"    # chess + emoji extended
    "\U0001FA70-\U0001FAFF"    # symbols & pictographs extended-A
    "\U00002600-\U000027BF"    # misc symbols + dingbats
    "\U00002B00-\U00002BFF"    # misc symbols & arrows
    "]+",
    flags=re.UNICODE,
)


def _strip_decorative_emojis(text: str) -> str:
    """Remueve emojis decorativos; preserva los del whitelist (📋).

    Implementación: sub() con función que filtra por whitelist por carácter.
    """
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        # Para cada carácter del match, preservar si está en whitelist.
        return "".join(
            c for c in match.group(0) if c in _ALLOWED_EMOJIS
        )

    cleaned = _EMOJI_PATTERN.sub(_replace, text)
    # Limpiar espacios duplicados que quedaron tras strip.
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" *\n", "\n", cleaned)
    return cleaned.strip()


class NoDecorativeEmojiInvariant:
    """Strip emojis decorativos del outbound (defensa en profundidad).

    El system_prompt ya prohíbe emojis, pero los LLMs a veces los
    insertan igualmente (especialmente al final de mensajes como
    "cierre amable"). Este invariant garantiza que NUNCA llegan al
    cliente.

    Whitelisted: 📋 (marcador estructural del resumen).
    """

    name = "no_decorative_emoji"

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
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        cleaned = _strip_decorative_emojis(candidate_text)
        if cleaned == candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=cleaned,
            reason="strip emojis decorativos (system_prompt regla #4)",
        )
