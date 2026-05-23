"""Mensajes degraded centralizados para mantener voz consistente.

ADR-0018. Cuando el agentic NO puede responder ideal (Gemini empty,
max turns excedido, safety block, etc.), entrega un mensaje degraded
preservando la persona conversacional ("Sara Camila") y el tono natural
del bot — NO lenguaje técnico de "error" / "procesando solicitud".

Principios de voz (rev. 107):
  • Natural, cordial colombiano. NO formal-corporativo.
  • Pide acción concreta al cliente cuando aplicable.
  • Promete escalamiento humano SOLO si la situación lo amerita
    (no resoluble por reformular).
  • Cero jerga técnica ("procesando", "complicación", "inconveniente").

Cada constante documenta su trigger contextual para evitar
re-introducción de mensajes ad-hoc en código.
"""

# ─── Recovery por finish_reason (agent.py::_recovery_strategy_for_finish_reason) ─

# SAFETY: Gemini bloqueó por filtros de seguridad. Mismo input → mismo
# bloqueo; no tiene sentido reintentar.
DEGRADED_SAFETY = "Mejor cuéntame de otra forma, ¿qué necesitas?"

# BLOCKLIST / PROHIBITED_CONTENT / SPII: contenido bloqueado por
# políticas. Mensaje claro pero sin culpar al cliente.
DEGRADED_BLOCKLIST = "Disculpa, ¿me lo dices de otra forma?"

# STOP/OTHER/UNKNOWN: el LLM "se confundió" momentáneamente. Pedir repetir
# es la respuesta más natural y sin tono robótico.
DEGRADED_GENERIC = "Ay, se me cruzó algo. ¿Me lo repites?"


# ─── Loop limits (agent.py main loop) ────────────────────────────────────

# Max tool turns excedido: el agente entró en loop con tools sin
# converger a una respuesta. Escala a humano porque reformular no resuelve.
DEGRADED_MAX_TOOL_TURNS = (
    "Voy a pedirle a un asesor que continúe contigo desde aquí. "
    "En un momento te contactan."
)

# Max tool calls excedido: similar al anterior pero el LLM hizo demasiados
# tool calls. Sugiere reformular antes de escalar.
DEGRADED_MAX_TOOL_CALLS = (
    "Cuéntame de nuevo qué necesitas en pocas palabras y te ayudo."
)
