"""``ConversationContext`` — el objeto que viaja por el coordinator.

Estructura inmutable (excepto las decisiones del turn) que captura todo lo
que un specialist necesita saber:

  - identificadores: tenant, conversation, message, contact, customer_phone
  - hechos del FSM: cart, contact_record, last_outbound_markers
  - inputs del turno: content, content_type, history
  - outputs del turno: cualquier estructura mutable que el coordinator
    consolide al final (no aquí — los specialists devuelven ``TurnResult``).

Coherente con el patrón "Functional Core, Imperative Shell" (Bernhardt):
los specialists son funciones puras que reciben context inmutable + repos
inyectados, y devuelven un ``TurnResult`` declarativo. El coordinator
ejecuta los efectos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.fsm import State


@dataclass
class ConversationContext:
    """Contexto inmutable de un turno conversacional.

    Construido por el coordinator a partir de los repos antes de invocar
    al specialist. Los specialists NO modifican este objeto — emiten
    :class:`TurnResult`.
    """

    # Identificadores ─────────────────────────────────────────────────────
    tenant_id: str
    conversation_id: str
    message_id: str
    contact_id: Optional[str]
    customer_phone: str  # ya normalizado (sin '+')

    # Inputs del turno ────────────────────────────────────────────────────
    content: str
    content_type: str  # text | image | audio | ...

    # Estado actual ───────────────────────────────────────────────────────
    fsm_state: State
    cart: Any  # Cart | None — del carts_repo
    contact_record: dict  # {name, email, phone, document_*, address, consent_given}
    history: list[dict]  # mensajes recientes

    # Catálogo + KB del tenant ───────────────────────────────────────────
    catalog: list[dict] = field(default_factory=list)
    kb_text: str = ""

    # Configuración del tenant ───────────────────────────────────────────
    tenant_name: str = ""
    tenant_tono: str = "amigable"
    tenant_escalation_role: str = "asesor"
    ai_agent: dict = field(default_factory=dict)

    # Banderas auxiliares ─────────────────────────────────────────────────
    is_first_outbound_in_conversation: bool = False
    last_outbound_was_consent_question: bool = False
    last_outbound_was_order_confirm_question: bool = False


class TurnDecisionKind(str, Enum):
    """Tipos de decisión que un specialist puede emitir."""

    SEND_TEXT = "send_text"           # enviar texto al cliente
    SEND_IMAGE = "send_image"         # enviar imagen + caption
    EXECUTE_TOOLS = "execute_tools"   # el LLM pidió tools — coordinator las ejecuta y reinvoca
    ESCALATE = "escalate"             # marcar conversación como human_takeover
    SKIP = "skip"                     # no hacer nada (mensaje irrelevante)
    ERROR = "error"                   # error tipado, ya logueado


@dataclass
class TurnResult:
    """Resultado declarativo de un turno.

    El coordinator interpreta este objeto y aplica los efectos:
      - SEND_TEXT/IMAGE → persiste outbound + envía a Meta
      - EXECUTE_TOOLS  → ejecuta tools, alimenta de vuelta al LLM
      - ESCALATE       → cambia status conversation + notifica
      - SKIP           → solo marca processed
      - ERROR          → marca skipped + razón
    """

    kind: TurnDecisionKind
    text: Optional[str] = None
    image_url: Optional[str] = None
    image_caption: Optional[str] = None
    tool_calls: list[Any] = field(default_factory=list)  # FunctionCall (de llm.parsers)
    escalation_reason: Optional[str] = None
    skip_reason: Optional[str] = None
    error: Optional[Exception] = None

    @classmethod
    def text(cls, content: str) -> "TurnResult":
        return cls(kind=TurnDecisionKind.SEND_TEXT, text=content)

    @classmethod
    def image(cls, url: str, caption: Optional[str] = None) -> "TurnResult":
        return cls(kind=TurnDecisionKind.SEND_IMAGE, image_url=url, image_caption=caption)

    @classmethod
    def execute_tools(cls, tool_calls: list[Any]) -> "TurnResult":
        return cls(kind=TurnDecisionKind.EXECUTE_TOOLS, tool_calls=tool_calls)

    @classmethod
    def escalate(cls, reason: str, message: Optional[str] = None) -> "TurnResult":
        return cls(
            kind=TurnDecisionKind.ESCALATE,
            text=message,
            escalation_reason=reason,
        )

    @classmethod
    def skip(cls, reason: str) -> "TurnResult":
        return cls(kind=TurnDecisionKind.SKIP, skip_reason=reason)

    @classmethod
    def error_result(cls, error: Exception) -> "TurnResult":
        return cls(kind=TurnDecisionKind.ERROR, error=error)
