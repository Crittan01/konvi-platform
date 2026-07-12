"""BLOQUE J-2 (auditoría 2026-07-12) — single source de los emojis permitidos.

Antes la whitelist se mantenía en 3 lugares (el invariant NoDecorativeEmoji + el
prompt V2 + el prompt V3) y ya había driftado: los prompts autorizaban 💵
(contraentrega) pero el invariant lo eliminaba en silencio (bug verificado). Este
módulo es la ÚNICA fuente: el invariant deriva el set de aquí y los prompts derivan
la línea de prosa de aquí → no pueden volver a discrepar.

Regla: WhatsApp más rico (faq.whatsapp.com/539178204879377) — CERO emojis
decorativos salvo estos marcadores estructurales/funcionales.
"""
from __future__ import annotations

# emoji → descripción funcional (orden = orden de aparición en el prompt).
ALLOWED_EMOJI_DESCRIPTIONS: dict[str, str] = {
    "📋": "resumen",
    "🚚": "envío",
    "✅": "pago confirmado",
    "💵": "contraentrega",
}

# Set consumido por el invariant NoDecorativeEmoji (lo que NO se elimina).
ALLOWED_EMOJIS: frozenset[str] = frozenset(ALLOWED_EMOJI_DESCRIPTIONS)


def allowed_emoji_prompt_line() -> str:
    """Línea de prosa para los prompts (V2/V3): '📋 (resumen), 🚚 (envío), ...'.
    Derivada del mismo mapa que consume el invariant → imposible que el prompt
    liste un emoji que el pipeline luego borre."""
    return ", ".join(
        f"{emoji} ({desc})" for emoji, desc in ALLOWED_EMOJI_DESCRIPTIONS.items()
    )
