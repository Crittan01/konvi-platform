"""State Machine determinístico del Inbox conversacional (rev. 109).

ADR-0019 — Agentic State Machine.

Motivación arquitectónica:
  • Gemini Flash saturaba con 15-19 tools + 17-19KB prompt + history extensa
    (AGENTIC_EMPTY_OUTPUT_DIAG en producción).
  • Industria (Kommo, Intercom, Crisp) usa state machine + per-state agents
    con tools subset reducidos.
  • Multi-tenant 2→100+ requiere agente production-grade.

Diseño:
  • Estado actual = función pura de (cart, contact, payments, orders, history).
  • LLM NO decide el estado — el resolver lo deriva.
  • Cada estado tendrá su propio mini-prompt (4-6KB) + tools subset (3-5).
  • Cache en conversations.agentic_state (rehidratable desde fuentes de verdad).

Esta capa expone:
  • AgenticState — enum canónico de estados.
  • StateResolver — derivador determinístico del estado actual.
  • Transitions — reglas FSM (qué estados son alcanzables desde X).
"""

from agentic.state_machine.states import AgenticState
from agentic.state_machine.resolver import StateResolver, ResolutionContext
from agentic.state_machine.transitions import (
    is_valid_transition,
    allowed_next_states,
    transition_reason,
)

__all__ = [
    "AgenticState",
    "StateResolver",
    "ResolutionContext",
    "is_valid_transition",
    "allowed_next_states",
    "transition_reason",
]
