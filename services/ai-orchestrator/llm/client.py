"""Wrapper de ``google-genai`` para el orquestador.

Punto de entrada único: :func:`invoke_llm`. Encapsula:
  - Construcción de ``GenerateContentConfig`` (system_instruction + tools +
    tool_config).
  - Restricción de tools por estado FSM via ``allowed_function_names``.
  - Parsing de la respuesta a :class:`llm.parsers.LlmTurn`.
  - Manejo defensivo de ``finishReason``.

NO contiene lógica de negocio. NO accede a Supabase. NO conoce el FSM —
recibe la lista de tools permitidos como parámetro.

Referencias:
  - SDK: https://googleapis.github.io/python-genai/
  - Function Calling: https://ai.google.dev/gemini-api/docs/function-calling
  - FunctionCallingConfig modes: AUTO | ANY | NONE | VALIDATED
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from llm.parsers import LlmTurn, parse_response
from llm.tool_specs import get_tool_specs

logger = logging.getLogger("orchestrator.llm.client")


# Modelo por defecto. Se respeta `LLM_MODEL` env var para A/B testing.
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# Temperatura conservadora — flujos transaccionales no quieren creatividad
# extra. Configurable via env para experimentación.
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))


def _import_genai():
    """Import diferido del SDK para no fallar en tests que no lo necesitan."""
    from google import genai  # type: ignore  # noqa: F401
    from google.genai import types  # type: ignore

    return genai, types


_genai_client_singleton: Optional[Any] = None


def get_client() -> Any:
    """Devuelve un cliente ``genai.Client`` reusable (singleton)."""
    global _genai_client_singleton
    if _genai_client_singleton is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY no configurada")
        genai, _types = _import_genai()
        _genai_client_singleton = genai.Client(api_key=api_key)
    return _genai_client_singleton


def invoke_llm(
    *,
    system_instruction: str,
    contents: list[Any],
    allowed_tools: frozenset[str] | set[str] | None = None,
    tool_mode: str = "AUTO",
    temperature: float = DEFAULT_TEMPERATURE,
    model: str = DEFAULT_MODEL,
    client: Any = None,
) -> LlmTurn:
    """Invoca Gemini con tools restringidos al estado FSM actual.

    Args:
      system_instruction: rol/persona/constraints globales (ver doc oficial,
        ``system_instruction`` en ``GenerateContentConfig``).
      contents: historial de turnos (``user``/``model``/``function``) según el
        formato del SDK. Para llamadas simples puede ser ``[{"role": "user",
        "parts": [{"text": "..."}]}]``.
      allowed_tools: nombres de tools permitidos en este turno. Si es None,
        se omite ``tool_config`` (modelo decide libremente sin restricción).
      tool_mode: ``AUTO`` (default), ``ANY`` (forzar function call), ``NONE``
        (deshabilitar), ``VALIDATED`` (Gemini 3+; reduce
        ``MALFORMED_FUNCTION_CALL``).
      temperature: 0.0-1.0. Default conservador 0.3.
      model: nombre del modelo. Default ``gemini-2.5-flash``.
      client: cliente ``genai.Client`` opcional (inyectable para tests).

    Returns:
      :class:`LlmTurn` con texto, function_calls y finish_reason ya parseados.
    """
    _genai, types = _import_genai()
    client = client or get_client()

    config_kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
    }

    if allowed_tools is not None and allowed_tools:
        tool_specs = get_tool_specs(allowed_tools)
        if tool_specs:
            config_kwargs["tools"] = [
                types.Tool(function_declarations=tool_specs)
            ]
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=tool_mode,
                    allowed_function_names=sorted(allowed_tools),
                )
            )
        else:
            logger.warning(
                "[llm.client] allowed_tools=%s no resolvió ningún spec",
                allowed_tools,
            )

    config = types.GenerateContentConfig(**config_kwargs)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    turn = parse_response(response)
    logger.info(
        "[llm.client] model=%s finish=%s n_calls=%d has_text=%s",
        model, turn.finish_reason.value, len(turn.function_calls),
        turn.text is not None,
    )
    return turn
