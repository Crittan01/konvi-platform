"""ToolDispatcher — orquestación determinística de tool handlers (rev. 104, F1-3).

Antes: orchestrator tenía un if/elif chain hardcoded llamando uno por uno
a los handlers `handle_X_if_applicable`. Cada handler decide internamente
si aplica (vía `_is_X_query` etc) y devuelve un resultado con `handled=True/False`.

Ahora: `ToolDispatcher` registra los handlers en orden de prioridad y los
despacha secuencialmente. El primer handler que retorna `handled=True` gana
y los siguientes se saltan. Si todos retornan `handled=False`, el caller
delega al LLM.

Beneficios estructurales:
  • Orden de evaluación explícito y testeable.
  • Agregar/remover tool sin tocar orchestrator monolito.
  • Logging uniforme de cuál tool atendió cada turno.
  • Estado dispatch trazable para audit (`bot_source_log.tool_handled`).

Diseño:
  • `ToolHandler`: callable async `(ctx) -> ToolResult`.
  • `ToolResult`: dataclass con `handled: bool`, `response_text`,
    `requires_human`, plus side-effects ya aplicados (DB writes).
  • `ToolDispatcher.dispatch(ctx)` itera y devuelve el primer hit + el nombre.

Tests: `tests/test_tool_dispatcher.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Contexto pasado a cada tool handler.

    Se construye una sola vez al inicio del turno y los handlers leen
    de aquí. Mantenerlo dataclass simple (no inheritance) para visibilidad.
    """
    supabase: Any
    tenant_id: str
    conversation_id: str
    contact_id: Optional[str]
    contact_record: dict
    content: str                       # inbound text actual
    history: list[dict]                # mensajes recientes
    catalog: list                      # catálogo del tenant
    display_state: str                 # FSM state ya resuelto
    metadata: dict = field(default_factory=dict)  # extension point


@dataclass
class ToolResult:
    """Resultado uniforme que cada tool handler debe devolver."""
    handled: bool
    response_text: Optional[str] = None
    requires_human: bool = False
    error: Optional[str] = None
    # Metadata libre para audit/log (e.g., {"tool": "shipping_quote", "city": "Bogotá"}).
    meta: dict = field(default_factory=dict)


# Tipo del callable que cada tool registra.
ToolHandler = Callable[[ToolContext], Awaitable[ToolResult]]


class ToolDispatcher:
    """Registra y despacha tool handlers en orden de prioridad.

    Uso:
        dispatcher = ToolDispatcher()
        dispatcher.register("image_send", image_handler)
        dispatcher.register("shipping_quote", shipping_handler)
        ...
        result, name = await dispatcher.dispatch(ctx)
        if result.handled:
            ...
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[str, ToolHandler]] = []

    def register(self, name: str, handler: ToolHandler) -> None:
        """Agrega un handler al final de la cadena de evaluación.

        El orden de registro define el orden de evaluación. El primer handler
        cuyo resultado tenga `handled=True` gana.
        """
        self._handlers.append((name, handler))

    @property
    def registered_tools(self) -> list[str]:
        return [name for name, _ in self._handlers]

    async def dispatch(self, ctx: ToolContext) -> tuple[ToolResult, Optional[str]]:
        """Itera handlers en orden hasta que uno responda `handled=True`.

        Returns:
            (result, tool_name) — `result.handled=False` y `tool_name=None`
            si ningún tool atendió (caller delega al LLM).
        """
        for name, handler in self._handlers:
            try:
                result = await handler(ctx)
            except Exception as exc:
                logger.exception(
                    "[TOOL_DISPATCHER] handler '%s' falló conv=%s: %s",
                    name, ctx.conversation_id[:8] if ctx.conversation_id else "?",
                    exc,
                )
                continue
            if result.handled:
                logger.info(
                    "[TOOL_DISPATCHER] handled by '%s' conv=%s",
                    name, ctx.conversation_id[:8] if ctx.conversation_id else "?",
                )
                return result, name
        return ToolResult(handled=False), None
