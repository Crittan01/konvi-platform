"""State Handler Layer — Sem 1 refactor (ADR-0017).

Consolida los 13 bypasses dispersos del orchestrator monolito en un set
de handlers per-state con contrato uniforme.

Public API:
  • StateHandler (Protocol)        — interface que cada handler implementa.
  • HandlerResult                  — output de un handler.
  • TurnInput                      — datos del turn que reciben los handlers.
  • dispatch                       — punto único de invocación.

Uso típico desde orchestrator:
  result = await dispatch(turn_input)
  if result is not None:
      # Handler resolvió determinísticamente — emit + return.
      ...
  else:
      # Ningún handler aplicó — continuar al LLM.
      ...
"""
from fsm.handlers.base import (
    HandlerResult,
    StateHandler,
    TurnInput,
)
from fsm.handlers.dispatcher import dispatch, get_handlers_for_state

__all__ = [
    "HandlerResult",
    "StateHandler",
    "TurnInput",
    "dispatch",
    "get_handlers_for_state",
]
