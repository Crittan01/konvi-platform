"""Core del orquestador conversacional.

Componentes:
  - :mod:`fsm`        — estados canónicos + transiciones permitidas + guards.
  - :mod:`context`    — ``ConversationContext`` que viaja por el coordinator.
  - :mod:`exceptions` — errores tipados.

NO depende de Supabase, LLM ni red. Lógica pura, testeable sin mocks pesados.
"""
