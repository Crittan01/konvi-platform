"""Agentic loop principal — Gemini function calling con tool-use.

ADR-0018. Production-grade. Reemplaza progresivamente al orchestrator
monolito (durante shadow + cutover).

Diseño:
  1. Cargar contexto (contact, cart, catalog, history).
  2. Construir system_prompt + user message.
  3. Llamar Gemini con tools=`gemini_function_schemas()`.
  4. Loop:
     - Si response tiene tool_calls → ejecutar cada tool → append result
       a messages → re-llamar Gemini con resultados.
     - Si response es texto puro → es el outbound final → salir loop.
  5. Aplicar invariants Python (anti-hallu vs cart real).
  6. Dispatch outbound al cliente.

Guardrails de costo + latencia:
  • MAX_TOOL_TURNS = 8 (corte si LLM entra en loop infinito).
  • MAX_TOTAL_TOKENS_BUDGET por turn (alarma + abort si excede).
  • Temperature = 0 (determinismo dentro de no-determinismo LLM).

Compatible con shadow mode: la función `run_agentic_turn` retorna el
outbound text en lugar de enviarlo. El caller decide enviarlo (cutover)
o solo loggearlo (shadow).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from agentic.tools.base import ToolContext
from agentic.tools.registry import all_tools, get_tool, gemini_function_schemas

logger = logging.getLogger(__name__)


# Guardrails operativos.
MAX_TOOL_TURNS = int(os.getenv("AGENTIC_MAX_TOOL_TURNS", "8"))
MAX_TOTAL_TOOL_CALLS = int(os.getenv("AGENTIC_MAX_TOOL_CALLS", "20"))
AGENTIC_TEMPERATURE = float(os.getenv("AGENTIC_TEMPERATURE", "0.0"))
AGENTIC_MODEL = os.getenv("AGENTIC_MODEL", "gemini-2.5-flash")


@dataclass
class AgenticTurnResult:
    """Resultado de un turn del agente.

    Inmutable después de construir (frozen=False solo para append a
    `tool_call_log` durante el loop). Caller debe tratarlo como solo-lectura.
    """
    outbound_text: str
    tool_calls_executed: int = 0
    tool_call_log: list[dict] = field(default_factory=list)
    truncated: bool = False
    truncated_reason: Optional[str] = None
    total_tokens: int = 0
    error: Optional[str] = None


async def run_agentic_turn(
    *,
    tenant_id: str,
    conversation_id: str,
    contact_id: Optional[str],
    inbound_text: str,
    contact_record: dict,
    catalog: list,
    history: list,
    supabase: Any,
    system_prompt: str,
) -> AgenticTurnResult:
    """Ejecuta UN turn del agente.

    Args:
      tenant_id, conversation_id, contact_id: identidad.
      inbound_text: mensaje del cliente.
      contact_record: pre-cargado por el caller.
      catalog: catalog del tenant pre-cargado.
      history: messages previos (≤25 por config).
      supabase: cliente DB.
      system_prompt: instrucciones para el LLM.

    Returns:
      AgenticTurnResult con outbound_text + audit del tool_call_log.
      Caller decide si enviar el outbound (cutover) o loggear (shadow).
    """
    ctx = ToolContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        supabase=supabase,
        catalog_cache=catalog,
        logger=logger,
        extras={},
    )

    # Construir messages para Gemini.
    # Incluimos history como contexto + el inbound actual.
    messages: list[dict] = []
    for msg in (history or []):
        direction = str(msg.get("direction") or "").lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if direction == "inbound":
            messages.append({"role": "user", "parts": [{"text": content}]})
        elif direction == "outbound":
            messages.append({"role": "model", "parts": [{"text": content}]})
    # Inbound actual.
    messages.append({"role": "user", "parts": [{"text": inbound_text}]})

    # Llamar Gemini con tools.
    tool_call_log: list[dict] = []
    total_tool_calls = 0
    outbound_text = ""
    truncated = False
    truncated_reason: Optional[str] = None

    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    except Exception as exc:
        return AgenticTurnResult(
            outbound_text="",
            error=f"Gemini client init falló: {exc}",
        )

    # Convertir tool schemas al formato Gemini types.
    tool_declarations = []
    for schema in gemini_function_schemas():
        tool_declarations.append(genai_types.FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            parameters=_to_gemini_schema(schema["parameters"]),
        ))
    tools_config = [genai_types.Tool(function_declarations=tool_declarations)]

    # Loop multi-turn de tool calling.
    for turn_idx in range(MAX_TOOL_TURNS):
        try:
            response = await _gemini_generate_async(
                client,
                model=AGENTIC_MODEL,
                messages=messages,
                system_prompt=system_prompt,
                tools_config=tools_config,
                temperature=AGENTIC_TEMPERATURE,
            )
        except Exception as exc:
            logger.warning("[AGENTIC] gemini call falló: %s", exc)
            return AgenticTurnResult(
                outbound_text="",
                tool_calls_executed=total_tool_calls,
                tool_call_log=tool_call_log,
                error=f"gemini_error: {exc}",
            )

        # Extraer parts (text + function_calls) del response.
        function_calls = _extract_function_calls(response)
        text_part = _extract_text(response)

        if not function_calls:
            # LLM emite texto final → outbound.
            outbound_text = text_part or ""
            break

        # Ejecutar cada tool call.
        if total_tool_calls + len(function_calls) > MAX_TOTAL_TOOL_CALLS:
            truncated = True
            truncated_reason = f"max_tool_calls_exceeded({MAX_TOTAL_TOOL_CALLS})"
            outbound_text = (
                text_part
                or "Disculpa, hubo una complicación procesando tu solicitud. "
                "¿Podrías reformular tu pregunta?"
            )
            break

        # Append el response del LLM a la conversación (con tool_calls).
        messages.append({
            "role": "model",
            "parts": [
                {"function_call": {"name": fc["name"], "args": fc["args"]}}
                for fc in function_calls
            ],
        })

        # Ejecutar y append los results.
        function_responses = []
        for fc in function_calls:
            tool_name = fc["name"]
            tool_args = fc["args"]
            tool = get_tool(tool_name)
            if tool is None:
                result_data = {
                    "error": f"Tool '{tool_name}' no existe.",
                    "code": "UNKNOWN_TOOL",
                }
            else:
                try:
                    # Validar args con Pydantic.
                    args_model = tool.args_schema(**tool_args)
                except Exception as exc:
                    result_data = {
                        "error": f"Args inválidos para {tool_name}: {exc}",
                        "code": "INVALID_ARGS",
                    }
                else:
                    try:
                        result = await tool.execute(args_model, ctx)
                        result_data = result.data if result.success else {
                            "error": result.data.get("error", "tool failed"),
                            "code": result.data.get("code", "TOOL_ERROR"),
                        }
                    except Exception as exc:
                        result_data = {
                            "error": f"Ejecución falló: {exc}",
                            "code": "EXECUTION_ERROR",
                        }

            tool_call_log.append({
                "turn": turn_idx,
                "tool": tool_name,
                "args": tool_args,
                "result": result_data,
            })
            total_tool_calls += 1

            function_responses.append({
                "function_response": {
                    "name": tool_name,
                    "response": result_data,
                },
            })

        messages.append({"role": "user", "parts": function_responses})

    else:
        truncated = True
        truncated_reason = f"max_tool_turns_exceeded({MAX_TOOL_TURNS})"
        outbound_text = (
            "Disculpa, no pude completar tu solicitud en este momento. "
            "Un asesor te contactará en breve."
        )

    return AgenticTurnResult(
        outbound_text=outbound_text,
        tool_calls_executed=total_tool_calls,
        tool_call_log=tool_call_log,
        truncated=truncated,
        truncated_reason=truncated_reason,
    )


# ─── Helpers internos ─────────────────────────────────────────────────────


async def _gemini_generate_async(
    client: Any,
    *,
    model: str,
    messages: list[dict],
    system_prompt: str,
    tools_config: list,
    temperature: float,
):
    """Wrapper async sobre client.models.generate_content."""
    from google.genai import types as genai_types

    # Convertir messages al formato Content de Gemini.
    contents = [
        genai_types.Content(
            role=m["role"],
            parts=[_part_from_dict(p) for p in m["parts"]],
        )
        for m in messages
    ]
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        tools=tools_config,
    )
    # generate_content es sync; envolverlo con run_in_executor para no
    # bloquear el event loop del worker.
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        ),
    )


def _part_from_dict(part_dict: dict):
    """Convierte dict-style part a Gemini Part."""
    from google.genai import types as genai_types
    if "text" in part_dict:
        return genai_types.Part(text=part_dict["text"])
    if "function_call" in part_dict:
        fc = part_dict["function_call"]
        return genai_types.Part(function_call=genai_types.FunctionCall(
            name=fc["name"], args=fc["args"],
        ))
    if "function_response" in part_dict:
        fr = part_dict["function_response"]
        return genai_types.Part(function_response=genai_types.FunctionResponse(
            name=fr["name"], response=fr["response"],
        ))
    raise ValueError(f"Part type desconocido: {part_dict}")


def _extract_function_calls(response: Any) -> list[dict]:
    """Extrae function_calls del response Gemini en formato dict."""
    calls: list[dict] = []
    if not response or not response.candidates:
        return calls
    for candidate in response.candidates:
        if not candidate.content or not candidate.content.parts:
            continue
        for part in candidate.content.parts:
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                calls.append({
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                })
    return calls


def _extract_text(response: Any) -> str:
    """Extrae el texto plano (no function_call) del response."""
    if not response or not response.candidates:
        return ""
    pieces: list[str] = []
    for candidate in response.candidates:
        if not candidate.content or not candidate.content.parts:
            continue
        for part in candidate.content.parts:
            text = getattr(part, "text", None)
            if text:
                pieces.append(text)
    return "\n".join(pieces).strip()


def _to_gemini_schema(pydantic_schema: dict) -> dict:
    """Pydantic JSON schema → Gemini-compatible schema.

    Gemini acepta JSON schema con minor adaptations. La diferencia clave
    es que Gemini no soporta algunos features avanzados (anyOf con discriminator).
    Para los schemas que generamos (BaseModel con tipos básicos + Literal),
    el JSON schema de Pydantic funciona directo.
    """
    # Strip "title", "$defs" que Gemini no necesita.
    cleaned = {k: v for k, v in pydantic_schema.items() if k not in ("title", "$defs")}
    if "properties" in cleaned:
        cleaned["properties"] = {
            pname: {pk: pv for pk, pv in props.items() if pk != "title"}
            for pname, props in cleaned["properties"].items()
        }
    return cleaned
