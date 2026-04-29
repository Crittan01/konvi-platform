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

# Modelo de fallback cuando el principal devuelve 503/UNAVAILABLE persistente
# tras los retries. ``gemini-2.5-flash-lite`` tiene menos demanda y es más
# rápido aunque menos capaz; suficiente para mantener la conversación viva
# durante un pico del modelo principal.
# Ref: https://ai.google.dev/gemini-api/docs/troubleshooting (sección rate limits)
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-2.5-flash-lite")

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

    # gemini-2.5-flash habilita "thinking" por default — el modelo gasta
    # tokens en razonamiento interno antes de emitir output. En flujos
    # transaccionales cortos (tool_use o respuesta breve) esto se manifiesta
    # como `finish=STOP` con `text=None` y `function_calls=[]` cuando el
    # budget se agota antes del output. Lo desactivamos.
    # Ref: https://ai.google.dev/gemini-api/docs/thinking
    try:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass

    # Deshabilitar AFC (Automatic Function Calling) del SDK. AFC ejecuta
    # function_calls internamente y solo expone el resultado final, lo que
    # rompe nuestro coordinator (que necesita ver y ejecutar las llamadas
    # explícitamente con acceso a Supabase, repos, etc.). Sin disable, en
    # mode=ANY el SDK puede entrar en bucles internos y devolver texto.
    # Ref: https://ai.google.dev/gemini-api/docs/function-calling
    try:
        config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable=True,
        )
    except Exception:
        pass

    if allowed_tools is not None and allowed_tools:
        tool_specs = get_tool_specs(allowed_tools)
        if tool_specs:
            # La restricción de qué tools puede ver el modelo se hace via el
            # array `tools` (le pasamos solo las permitidas en este estado).
            # `allowed_function_names` es un mecanismo SECUNDARIO que solo
            # acepta Gemini cuando `mode in {ANY, VALIDATED}` — con AUTO/NONE
            # el API rechaza con INVALID_ARGUMENT.
            # Ref: https://ai.google.dev/gemini-api/docs/function-calling
            config_kwargs["tools"] = [
                types.Tool(function_declarations=tool_specs)
            ]
            fc_kwargs: dict = {"mode": tool_mode}
            if tool_mode.upper() in {"ANY", "VALIDATED"}:
                fc_kwargs["allowed_function_names"] = sorted(allowed_tools)
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(**fc_kwargs)
            )
        else:
            logger.warning(
                "[llm.client] allowed_tools=%s no resolvió ningún spec",
                allowed_tools,
            )

    config = types.GenerateContentConfig(**config_kwargs)

    # Retry con backoff para errores transitorios + fallback a modelo
    # alternativo si los retries fallan. Pattern documentado:
    # https://ai.google.dev/gemini-api/docs/troubleshooting
    import time
    response = None
    models_to_try = [model]
    if FALLBACK_MODEL and FALLBACK_MODEL != model:
        models_to_try.append(FALLBACK_MODEL)

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )
                if model_idx > 0:
                    logger.info(
                        "[llm.client] fallback exitoso a model=%s tras 503 en %s",
                        current_model, models_to_try[0],
                    )
                break  # éxito — salir del loop interno
            except Exception as exc:
                msg = str(exc)
                transient = (
                    "503" in msg or "UNAVAILABLE" in msg
                    or "429" in msg or "RESOURCE_EXHAUSTED" in msg
                    or "DEADLINE_EXCEEDED" in msg
                )
                if not transient:
                    raise  # no retry para errores no transitorios
                if attempt < 2:
                    backoff = 1.5 * (2 ** attempt)  # 1.5s, 3s
                    logger.warning(
                        "[llm.client] %s transient attempt=%d backoff=%.1fs err=%s",
                        current_model, attempt + 1, backoff,
                        msg.split('\n')[0][:120],
                    )
                    time.sleep(backoff)
                else:
                    # Último intento de este modelo. Si hay fallback disponible,
                    # cambiamos al siguiente; si no, propagamos.
                    if model_idx + 1 < len(models_to_try):
                        logger.warning(
                            "[llm.client] %s falló 3 veces — cambio a fallback %s",
                            current_model, models_to_try[model_idx + 1],
                        )
                    else:
                        raise
        else:
            continue  # el loop interno no rompió → probar siguiente modelo
        break  # éxito

    turn = parse_response(response)
    if not turn.function_calls and not turn.text:
        logger.warning(
            "[llm.client] respuesta vacía — raw=%s",
            getattr(response, "to_json_dict", lambda: str(response))(),
        )
    elif tool_mode and tool_mode.upper() == "ANY" and not turn.function_calls:
        logger.warning(
            "[llm.client] mode=ANY pero LLM emitió texto sin tool — "
            "candidates=%s",
            getattr(response, "candidates", None),
        )
    logger.info(
        "[llm.client] model=%s finish=%s n_calls=%d has_text=%s",
        model, turn.finish_reason.value, len(turn.function_calls),
        turn.text is not None,
    )
    return turn
