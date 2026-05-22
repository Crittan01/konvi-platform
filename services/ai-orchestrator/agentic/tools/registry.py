"""Registry global de tools agentic.

ADR-0018 Sem 0 MVP.

Diseño:
  • Cada tool se registra al importar su módulo vía `register_tool(MyTool())`.
  • `gemini_function_schemas()` genera las function definitions para
    pasarle a Gemini en la llamada (formato OpenAI/Gemini compatible).
  • `get_tool(name)` lookup O(1) cuando el LLM invoca por name.

Observabilidad:
  • Cada tool execution se loggea con name, args (sanitizados), result
    success/failure, latency. Útil para audit + debug + cost tracking.
"""
from __future__ import annotations

import logging
from typing import Optional

from agentic.tools.base import Tool

logger = logging.getLogger(__name__)

# Registry global keyed por tool name.
_TOOLS: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    """Registra un tool en el registry.

    Idempotente por nombre: re-registrar reemplaza la versión anterior
    (útil para tests o hot-reload). En producción cada tool se registra
    exactamente una vez al importar su módulo.
    """
    if not tool.name:
        raise ValueError("Tool sin name")
    if tool.name in _TOOLS:
        logger.debug("[TOOL_REGISTRY] reemplazando tool name=%s", tool.name)
    _TOOLS[tool.name] = tool


def unregister_tool(name: str) -> None:
    """Remueve un tool por nombre (útil para tests)."""
    _TOOLS.pop(name, None)


def clear_registry() -> None:
    """Vacía el registry (solo tests)."""
    _TOOLS.clear()


def get_tool(name: str) -> Optional[Tool]:
    """Lookup de tool por name. Returns None si no existe."""
    return _TOOLS.get(name)


def all_tools() -> list[Tool]:
    """Lista de todos los tools registrados. Útil para introspección
    + para pasarle a Gemini el set completo."""
    return list(_TOOLS.values())


def gemini_function_schemas() -> list[dict]:
    """Genera las function definitions en formato Gemini para pasarle
    al modelo en la llamada `generate_content(tools=[...])`.

    Formato (Gemini):
      {
        "name": "tool_name",
        "description": "...",
        "parameters": <JSON schema from Pydantic>
      }

    Pydantic.model_json_schema() produce JSON schema estándar que Gemini
    acepta directamente (con algunas adaptaciones menores).
    """
    schemas: list[dict] = []
    for tool in _TOOLS.values():
        try:
            params_schema = tool.args_schema.model_json_schema()
        except Exception as exc:
            logger.warning(
                "[TOOL_REGISTRY] schema gen falló tool=%s: %s",
                tool.name, exc,
            )
            continue
        # Pydantic incluye "title" y "$defs" que Gemini no necesita; los
        # dejamos por compatibilidad — Gemini los ignora.
        schemas.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": params_schema,
        })
    return schemas
