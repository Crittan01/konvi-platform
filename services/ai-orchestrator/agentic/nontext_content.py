"""Manejo seguro de content_types entrantes no-texto y no-multimodal.

F5 bot_engine (decisión #3). El pipeline multimodal (agentic/multimodal.py)
cubre audio/image/video → transcripción Gemini. Pero WhatsApp también envía
`document`, `sticker` y `location`, que ANTES caían al flujo agentic como si
su placeholder ("[Documento recibido]", "[Ubicación recibida]") fuera un
mensaje de texto del cliente → el LLM improvisaba sobre un input sin señal.

Política (decisión founder, alcance ai-orchestrator):
  • document → derivar a HUMANO. Riesgo alto de fraude/alucinación si el bot
    intenta "interpretar" un comprobante de pago PDF. El bot NO decide verdad
    transaccional (principio crítico #4). Interpretación de comprobantes queda
    fuera de scope del bot por ahora.
  • location → NO se puede reverse-geocodear aún (lat/long no persistido por el
    connector + proveedor de geocoding sin definir → external_blocked). En vez
    de descartar la señal en silencio, pedimos ciudad/dirección en texto para
    autollenar el envío. Degrada seguro sin perder la intención de compra.
  • sticker → señal social sin texto. Respuesta cálida + reencauzar a la
    necesidad real. NO escalar (ruido inofensivo).

Este módulo es PURO (sin I/O) → testeable. El dispatcher hace el side-effect
(enviar outbound, escalar, marcar procesado) reusando helpers existentes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# content_types que este módulo gobierna (los que NO pasan por multimodal ni
# son texto/interactive/button). Set explícito → un tipo nuevo desconocido
# recibe el trato genérico seguro vía `handle_nontext_content` fallback.
NONTEXT_CONTENT_TYPES = frozenset({"document", "sticker", "location"})


@dataclass(frozen=True)
class NonTextResponse:
    """Decisión determinística de cómo responder a un inbound no-texto.

    Campos:
      • reply_text: outbound al cliente (nunca vacío).
      • escalate: si True, el dispatcher marca human_takeover + notifica al
        equipo (el bot deja de responder este hilo).
      • escalation_reason: motivo forense para el audit/Telegram (si escalate).
    """
    reply_text: str
    escalate: bool = False
    escalation_reason: Optional[str] = None


# Mensajes determinísticos (no LLM → sin costo, sin alucinación).
_MSG_DOCUMENT = (
    "Recibí tu documento. Para revisarlo con el cuidado que merece te voy a "
    "conectar con un especialista de mi equipo, que te escribe en un momento. "
    "Si es algo que yo pueda ayudarte a resolver por aquí, cuéntame en un "
    "mensaje y con gusto sigo."
)
_MSG_LOCATION = (
    "Gracias por compartir tu ubicación. Para cotizar el envío necesito la "
    "ciudad y la dirección escritas. Me las puedes enviar en un mensaje? "
    "Ejemplo: \"Bogotá, Calle 123 #45-67\"."
)
_MSG_STICKER = (
    "Jaja gracias! Cuéntame, en qué te puedo ayudar hoy?"
)
_MSG_GENERIC = (
    "Recibí tu mensaje, pero por aquí solo puedo leer texto. Me cuentas en "
    "palabras qué necesitas y con gusto te ayudo?"
)


def handle_nontext_content(content_type: str) -> Optional[NonTextResponse]:
    """Decide la respuesta segura para un content_type no-texto/no-multimodal.

    Returns:
      NonTextResponse si `content_type` es uno gobernado por este módulo (o un
      tipo desconocido no-manejado en otra parte); None si el content_type NO
      corresponde a este módulo (texto, audio/image/video, interactive, button)
      → el caller sigue su flujo normal.
    """
    ct = (content_type or "").strip().lower()
    if ct == "document":
        return NonTextResponse(
            reply_text=_MSG_DOCUMENT,
            escalate=True,
            escalation_reason=(
                "cliente envió un documento (posible comprobante) — revisión "
                "humana por riesgo de fraude/interpretación"
            ),
        )
    if ct == "location":
        return NonTextResponse(reply_text=_MSG_LOCATION)
    if ct == "sticker":
        return NonTextResponse(reply_text=_MSG_STICKER)
    return None
