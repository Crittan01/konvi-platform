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

from agentic.degraded_messages import (
    DEGRADED_BLOCKLIST,
    DEGRADED_GENERIC,
    DEGRADED_MAX_TOOL_CALLS,
    DEGRADED_MAX_TOOL_TURNS,
    DEGRADED_SAFETY,
)
from agentic.tools.base import ToolContext
from agentic.tools.registry import get_tool, gemini_function_schemas

logger = logging.getLogger(__name__)


# Guardrails operativos.
MAX_TOOL_TURNS = int(os.getenv("AGENTIC_MAX_TOOL_TURNS", "8"))
MAX_TOTAL_TOOL_CALLS = int(os.getenv("AGENTIC_MAX_TOOL_CALLS", "20"))
AGENTIC_TEMPERATURE = float(os.getenv("AGENTIC_TEMPERATURE", "0.0"))
AGENTIC_MODEL = os.getenv("AGENTIC_MODEL", "gemini-3.1-flash-lite")
# Fix latencia (2026-07-07): sin timeout, si el modelo primario se satura (503
# "high demand"), el SDK de Gemini reintenta con backoff SIN límite → un turno
# tardaba ~160s. Con timeout por llamada, el modelo lento falla rápido y el
# cascade promueve al fallback (gemini-3.1-flash-lite) → respuesta en segundos.
AGENTIC_LLM_TIMEOUT_MS = int(os.getenv("AGENTIC_LLM_TIMEOUT_MS", "30000"))  # 30s/llamada

# Reuso del cliente Gemini por proceso (perf rev. 114). Antes se creaba un
# genai.Client —y su pool TLS— en CADA mensaje. El worker es single-thread
# secuencial (server.py corre el loop en su propio hilo), así que reusar un
# cliente por api_key es seguro y ahorra el handshake TLS por turno. Cacheado por
# api_key para no filtrar entre entornos/tests con distinta key.
_GENAI_CLIENTS: dict = {}


def _get_genai_client(genai, genai_types):
    """Devuelve un genai.Client reusado por proceso/api_key (no uno nuevo por turno)."""
    api_key = os.getenv("GEMINI_API_KEY") or ""
    client = _GENAI_CLIENTS.get(api_key)
    if client is None:
        client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=AGENTIC_LLM_TIMEOUT_MS),
        )
        _GENAI_CLIENTS[api_key] = client
    return client
# thinking_budget del turno agéntico. Opcional (solo se aplica si el env está
# seteado, para no cambiar la coherencia validada sin querer): 0 = sin thinking
# (más rápido); un entero = presupuesto de tokens de razonamiento.
AGENTIC_THINKING_BUDGET = os.getenv("AGENTIC_THINKING_BUDGET")  # str | None


@dataclass
class AgenticTurnResult:
    """Resultado de un turn del agente.

    Inmutable después de construir (frozen=False solo para append a
    `tool_call_log` durante el loop). Caller debe tratarlo como solo-lectura.

    Campos de trazabilidad (rev. 107 cierre arquitectónico):
      • `finish_reason`: último valor reportado por Gemini ("STOP",
        "MAX_TOKENS", "SAFETY", etc.). None si el turn cerró por tool-call
        path sin pasar por evaluación de finish_reason vacío.
    """
    outbound_text: str
    tool_calls_executed: int = 0
    tool_call_log: list[dict] = field(default_factory=list)
    truncated: bool = False
    truncated_reason: Optional[str] = None
    total_tokens: int = 0
    # Track 6 (2026-08-22): breakdown de uso para medir implicit caching
    # (fase 0 del ahorro — la doc no garantiza caching en flash-lite; medir).
    prompt_tokens: int = 0
    cached_tokens: int = 0
    thoughts_tokens: int = 0
    error: Optional[str] = None
    finish_reason: Optional[str] = None
    # Rev. 107 founder feedback: cuando el agentic agota todas las recoveries
    # (retry history-5 + text-only retry) y aun así no logra outbound útil,
    # marcar este flag para que el dispatcher escale silenciosamente al
    # equipo (status=human_takeover). Evita que el cliente perciba al bot
    # como "mudo" o "atorado". Mensaje natural ("ya te respondo") +
    # operador toma el control en el Inbox.
    requires_silent_escalation: bool = False


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
    allowed_tools: Optional[set[str]] = None,
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
      allowed_tools: rev. 109 — set de tool names expuestos al LLM.
        None → todos los tools registrados (legacy/fallback). Per-state
        subset reduce carga cognitiva del modelo.

    Returns:
      AgenticTurnResult con outbound_text + audit del tool_call_log.
      Caller decide si enviar el outbound (cutover) o loggear (shadow).
    """
    # Rev. 107 fix runtime KAIU 2026-05-24: pasamos al ctx el inbound
    # actual + los 2 últimos inbounds previos del history para que el
    # AddToCartTool pueda verificar que la variante que el LLM intenta
    # agregar fue realmente mencionada por el cliente (anti-asunción).
    # OJO: `_get_conversation_history` devuelve filas con `direction`/`content`, NO con
    # `role`. El código de abajo preguntaba por `h.get("role") == "user"`, condición que
    # NUNCA se cumplía: esta lista llevaba solo el inbound actual desde que se escribió,
    # aunque el comentario prometiera los tres últimos.
    #
    # Consecuencia: el guardián anti-adivinanza de `add_to_cart` juzgaba con UN mensaje. Si
    # el cliente decía "el de avena y miel, el más grande" y en el turno siguiente "sí,
    # agrégalo", el guardián solo veía "sí, agrégalo", no encontraba variante mencionada y
    # rechazaba — obligando a repetir algo que el cliente ya había dicho.
    #
    # Se aceptan las dos formas: la del history real (`direction`) y la de tipo chat
    # (`role`), que es la que usan los tests y algún caller.
    _recent_inbounds = [inbound_text]
    for h in reversed(history or []):
        if len(_recent_inbounds) >= 3:
            break
        if not isinstance(h, dict):
            continue
        content = h.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        es_del_cliente = (
            h.get("direction") == "inbound" or h.get("role") == "user"
        )
        if es_del_cliente:
            _recent_inbounds.append(content)
    ctx = ToolContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        supabase=supabase,
        catalog_cache=catalog,
        logger=logger,
        extras={"recent_inbound_texts": _recent_inbounds},
    )

    # Construir messages para Gemini.
    messages = _build_gemini_messages(history, inbound_text)

    # Llamar Gemini con tools.
    tool_call_log: list[dict] = []
    total_tool_calls = 0
    outbound_text = ""
    truncated = False
    truncated_reason: Optional[str] = None
    # Trazabilidad rev. 107: capturar finish_reason del último response
    # del LLM en TODOS los paths (texto, tool, empty). Se persiste en
    # agentic_turn_audit para diagnosticar runtime sin depender de logs
    # stdout (que rotan).
    last_finish_reason: Optional[str] = None
    # F5 telemetría de costo (decisión bot_engine #2): acumular tokens de
    # TODOS los responses Gemini del turn (loop multi-tool + fallbacks).
    # Se persiste en agentic_shadow_log.total_tokens → costo LLM por tenant,
    # insumo directo de pricing/límites. Best-effort: si el SDK no reporta
    # usage_metadata, queda 0 (nunca rompe el turn).
    # Track 6 (2026-08-22): + breakdown prompt/cached/thoughts (fase 0 caching).
    total_tokens = 0
    usage_breakdown = {"prompt_tokens": 0, "cached_tokens": 0, "thoughts_tokens": 0}

    try:
        from google import genai
        from google.genai import types as genai_types
        client = _get_genai_client(genai, genai_types)
    except Exception as exc:
        return AgenticTurnResult(
            outbound_text="",
            error=f"Gemini client init falló: {exc}",
        )

    # Convertir tool schemas al formato Gemini types.
    # Rev. 109 — filtrar por allowed_tools (per-state subset). Si None,
    # exponemos todos los tools registrados (compat legacy).
    tool_declarations = []
    for schema in gemini_function_schemas():
        if allowed_tools is not None and schema["name"] not in allowed_tools:
            continue
        tool_declarations.append(genai_types.FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            parameters=_to_gemini_schema(schema["parameters"]),
        ))
    tools_config = [genai_types.Tool(function_declarations=tool_declarations)]
    if allowed_tools is not None:
        logger.info(
            "[AGENTIC] per-state subset tools=%d (allowed=%d)",
            len(tool_declarations), len(allowed_tools),
        )

    # Loop multi-turn de tool calling.
    # Tracking de recovery empty_output (1 retry max por turn).
    empty_recovery_attempt = 0
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
                finish_reason=last_finish_reason,
                total_tokens=total_tokens,
                prompt_tokens=usage_breakdown["prompt_tokens"],
                cached_tokens=usage_breakdown["cached_tokens"],
                thoughts_tokens=usage_breakdown["thoughts_tokens"],
            )

        # Extraer parts (text + function_calls) del response.
        function_calls = _extract_function_calls(response)
        text_part = _extract_text(response)
        # Capturar finish_reason de TODOS los responses (texto/tool/empty).
        last_finish_reason = _extract_finish_reason(response) or last_finish_reason
        _usage = _extract_usage(response)
        total_tokens += _usage["total_tokens"]
        for _k in usage_breakdown:
            usage_breakdown[_k] += _usage[_k]

        # Manejo activo empty_output (rev. 107): si Gemini retorna response
        # sin tools y sin texto, detectar finish_reason y aplicar strategy
        # de recovery por finishReason en vez de raise. Cierra la deuda
        # arquitectónica de la primera versión que trataba esto como excepción.
        if not function_calls and not text_part:
            finish_reason = last_finish_reason

            # Instrumentación rev. 107: log estructurado del contexto cuando
            # Gemini retorna empty. Captura las variables que probable-
            # mente correlacionan con la causa raíz (prompt saturation,
            # tool count alto, history demasiado largo) para diagnosticar
            # patrones SIN heurísticas ciegas. No altera comportamiento.
            try:
                tools_count = sum(
                    len(getattr(t, "function_declarations", []) or [])
                    for t in (tools_config or [])
                )
                msgs_chars = sum(
                    len(str(m.get("parts") or "")) for m in messages
                )
                last_user_chars = 0
                for m in reversed(messages):
                    if m.get("role") == "user":
                        last_user_chars = len(str(m.get("parts") or ""))
                        break
                logger.warning(
                    "[AGENTIC_EMPTY_OUTPUT_DIAG] conv=%s tenant=%s "
                    "finish_reason=%s history_turns=%d tools_count=%d "
                    "msgs_chars=%d last_user_chars=%d system_prompt_chars=%d "
                    "recovery_attempt=%d tool_calls_so_far=%d",
                    conversation_id, tenant_id,
                    finish_reason or "UNKNOWN",
                    len(messages), tools_count, msgs_chars, last_user_chars,
                    len(system_prompt or ""),
                    empty_recovery_attempt, total_tool_calls,
                )
            except Exception as _diag_exc:
                # Diagnostics NO bloquea el flujo de recovery.
                logger.debug("[AGENTIC_EMPTY_OUTPUT_DIAG] log falló: %s", _diag_exc)

            degraded_text, should_retry, retry_history_limit = (
                _recovery_strategy_for_finish_reason(
                    finish_reason, empty_recovery_attempt,
                )
            )
            logger.info(
                "[AGENTIC_EMPTY_OUTPUT] conv=%s finish_reason=%s "
                "attempt=%d strategy=%s",
                conversation_id,
                finish_reason or "UNKNOWN",
                empty_recovery_attempt,
                "retry" if should_retry else "degraded",
            )

            if should_retry:
                empty_recovery_attempt += 1
                # Reducir history para retry (estrategia depende del finish_reason).
                if retry_history_limit > 0 and len(messages) > retry_history_limit:
                    # Preservar el último user message + los N más recientes.
                    messages = messages[-retry_history_limit:]
                # Re-loop con history ajustado (vuelve al try).
                continue

            # Rev. 107 — último intento antes de degraded: text-only sin
            # tools_config. Causa raíz observada (caso "sérums" KAIU 2026-
            # 05-23): system_prompt 13k + 16 tools + categoría con tilde
            # → Gemini "no decide" qué tool llamar y retorna empty. Sin
            # tools en el config, el modelo está forzado a emitir texto.
            # Si emite, mejor que degraded; si sigue empty, ahí sí degraded.
            if empty_recovery_attempt >= 1 and finish_reason == "STOP":
                logger.info(
                    "[AGENTIC_EMPTY_OUTPUT] conv=%s última oportunidad: "
                    "retry sin tools (text-only)",
                    conversation_id,
                )
                try:
                    fallback_response = await _gemini_generate_async(
                        client,
                        model=AGENTIC_MODEL,
                        messages=messages,
                        system_prompt=system_prompt,
                        tools_config=None,  # ← key: sin tools
                        temperature=AGENTIC_TEMPERATURE,
                    )
                    fallback_text = _extract_text(fallback_response) or ""
                    last_finish_reason = (
                        _extract_finish_reason(fallback_response)
                        or last_finish_reason
                    )
                    total_tokens += _extract_total_tokens(fallback_response)
                    _fu = _extract_usage(fallback_response)
                    for _k in usage_breakdown:
                        usage_breakdown[_k] += _fu[_k]
                    if fallback_text.strip():
                        outbound_text = fallback_text
                        # Marcar como "recovered" — no degraded.
                        truncated = True
                        truncated_reason = (
                            f"recovered_text_only_from:{finish_reason or 'STOP'}"
                        )
                        logger.info(
                            "[AGENTIC_EMPTY_OUTPUT] conv=%s text-only retry OK "
                            "(chars=%d)",
                            conversation_id, len(fallback_text),
                        )
                        break
                except Exception as fb_exc:
                    logger.warning(
                        "[AGENTIC] text-only fallback falló: %s", fb_exc,
                    )

            # ── Recoveries reales agotados ──
            # (A6 2026-08-02: el tier Claude rescue se eliminó — el paquete
            # `anthropic` nunca estuvo en requirements, así que is_available()
            # era siempre False y el tier era código muerto. Los recoveries
            # reales que quedan: retry con history reducido y retry text-only,
            # ambos arriba.)
            # No retry — usar degraded text como outbound.
            # Marcar requires_silent_escalation si agotamos recoveries STOP.
            # El dispatcher debe escalar conv a human_takeover para que un
            # especialista intervenga ANTES de que el cliente perciba el
            # bot "atorado".
            outbound_text = degraded_text
            truncated = True
            truncated_reason = f"empty_output:{finish_reason or 'UNKNOWN'}"
            requires_silent_escalation_flag = (
                finish_reason in ("STOP", "OTHER", "")
                and empty_recovery_attempt >= 1
            )
            return AgenticTurnResult(
                outbound_text=outbound_text,
                tool_calls_executed=total_tool_calls,
                tool_call_log=tool_call_log,
                truncated=truncated,
                truncated_reason=truncated_reason,
                finish_reason=last_finish_reason,
                requires_silent_escalation=requires_silent_escalation_flag,
                total_tokens=total_tokens,
                prompt_tokens=usage_breakdown["prompt_tokens"],
                cached_tokens=usage_breakdown["cached_tokens"],
                thoughts_tokens=usage_breakdown["thoughts_tokens"],
            )

        if not function_calls:
            # LLM emite texto final → outbound.
            outbound_text = text_part or ""
            break

        # Ejecutar cada tool call.
        if total_tool_calls + len(function_calls) > MAX_TOTAL_TOOL_CALLS:
            truncated = True
            truncated_reason = f"max_tool_calls_exceeded({MAX_TOTAL_TOOL_CALLS})"
            outbound_text = text_part or DEGRADED_MAX_TOOL_CALLS
            break

        # Append el response del LLM a la conversación (con tool_calls).
        messages.append({
            "role": "model",
            "parts": [
                {
                    "function_call": {"name": fc["name"], "args": fc["args"]},
                    # Gemini 3.x: preservar la firma para el round-trip de tools.
                    "thought_signature": fc.get("thought_signature"),
                }
                for fc in function_calls
            ],
        })

        # Ejecutar y append los results.
        function_responses = []
        for fc in function_calls:
            tool_name = fc["name"]
            tool_args = fc["args"]
            # BLOQUE J-3 (audit): enforcement en RUNTIME de allowed_tools. El filtro
            # de arriba solo le DICE a Gemini qué tools tiene declarados; si el LLM
            # invoca uno FUERA de su subset (hallucinación / drift entre el subset
            # per-state y lo declarado), aquí se bloquea ANTES de ejecutar —
            # defense-in-depth, no depender de la adherencia del modelo. Cierra el
            # bypass de guardrails per-tenant/per-state a nivel de ejecución.
            if allowed_tools is not None and tool_name not in allowed_tools:
                logger.warning(
                    "[AGENTIC] tool '%s' FUERA de allowed_tools (%d permitidos) — "
                    "bloqueado en runtime (no ejecutado)",
                    tool_name, len(allowed_tools),
                )
                result_data = {
                    "error": (
                        f"Tool '{tool_name}' no está disponible en este estado de "
                        "la conversación."
                    ),
                    "code": "TOOL_NOT_ALLOWED",
                }
                tool_call_log.append({
                    "turn": turn_idx, "tool": tool_name,
                    "args": tool_args, "result": result_data,
                })
                total_tool_calls += 1
                function_responses.append({
                    "function_response": {"name": tool_name, "response": result_data},
                })
                continue
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
                    # Fase 2 finiquito 2026-06-23 — Pre-tool invariant binario
                    # `tool_id_referential_integrity` (ADR-0024). Cierra BUG-CART-1:
                    # LLM hallucinaba UUIDs en add_to_cart/update_cart_item_quantity/
                    # remove_cart_item. Esta capa bloquea ANTES de tool.execute si el
                    # ID no está en el catalog inyectado al prompt, retornando un
                    # error con code MUST_LIST_CATALOG_FIRST que fuerza al LLM a
                    # auto-recuperarse via list_catalog.
                    from agentic.invariants.tool_id_referential_integrity import (
                        check_tool_id_referential_integrity,
                    )
                    _pre_tool_block = check_tool_id_referential_integrity(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        catalog=catalog,
                    )
                    if _pre_tool_block is not None:
                        result_data = _pre_tool_block
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
        outbound_text = DEGRADED_MAX_TOOL_TURNS

    return AgenticTurnResult(
        outbound_text=outbound_text,
        tool_calls_executed=total_tool_calls,
        tool_call_log=tool_call_log,
        truncated=truncated,
        truncated_reason=truncated_reason,
        finish_reason=last_finish_reason,
        total_tokens=total_tokens,
        prompt_tokens=usage_breakdown["prompt_tokens"],
        cached_tokens=usage_breakdown["cached_tokens"],
        thoughts_tokens=usage_breakdown["thoughts_tokens"],
    )


# ─── Helpers internos ─────────────────────────────────────────────────────


def _build_gemini_messages(
    history: Optional[list],
    inbound_text: str,
) -> list[dict]:
    """Construye el array `messages` para Gemini desde history + inbound.

    Rev. 107: bug runtime KAIU conv 8f96520e — `save_name(value='Cristian
    GarzónCristian Garzón')`. Causa: el dispatcher carga history desde DB
    DESPUÉS de que el inbound nuevo ya fue persistido. El history ya
    contiene el inbound actual como último user message; al re-añadirlo
    al final, Gemini ve el mismo texto 2 veces consecutivas y compone
    args concatenados (rompe TODO tool con `value` de texto libre:
    save_name, save_email, consent_text, save_address...).

    Fix: dedupe — si el último inbound del history coincide (case+strip)
    con `inbound_text`, omitirlo. Función pura testeable.
    """
    history_list = list(history or [])
    if history_list:
        last = history_list[-1]
        last_is_same_inbound = (
            str(last.get("direction") or "").lower() == "inbound"
            and str(last.get("content") or "").strip()
            == (inbound_text or "").strip()
        )
        if last_is_same_inbound:
            history_list = history_list[:-1]

    messages: list[dict] = []
    for msg in history_list:
        direction = str(msg.get("direction") or "").lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if direction == "inbound":
            messages.append({"role": "user", "parts": [{"text": content}]})
        elif direction == "outbound":
            messages.append({"role": "model", "parts": [{"text": content}]})
    messages.append({"role": "user", "parts": [{"text": inbound_text}]})
    return messages


async def _gemini_generate_async(
    client: Any,
    *,
    model: str,
    messages: list[dict],
    system_prompt: str,
    tools_config: list,
    temperature: float,
):
    """Wrapper async sobre client.models.generate_content con cascada.

    Rev. 106 — envuelve la invocación en `generate_with_cascade` de
    `llm_invoke.py` (Rev. 80, ADR-0001). Garantiza:
      • Intentos en `model` (primary) con backoff exponencial 1-16s
        (GEMINI_FALLBACK_AFTER, default 2) y presupuesto total por turno
        (LLM_CASCADE_DEADLINE_SECONDS, default 100s — A5 2026-08-02).
      • Resto de intentos en `GEMINI_FALLBACK_MODEL` (default gemini-3.5-flash)
        si el primary mantiene 503/429.
      • Errores no-transitorios (bug schema/prompt) se re-lanzan inmediato.
      • Si TODOS los intentos transitorios fallan → raise
        `gemini_cascade_exhausted` para que el dispatcher responda degraded
        + escale (V1 legacy retirado, BLOQUE K-2).

    Previo a rev. 106: 1 intento, sin retry, 503 colapsaba directamente.
    """
    from google.genai import types as genai_types
    from llm_invoke import generate_with_cascade

    # Convertir messages al formato Content de Gemini.
    contents = [
        genai_types.Content(
            role=m["role"],
            parts=[_part_from_dict(p) for p in m["parts"]],
        )
        for m in messages
    ]
    _cfg_kwargs = dict(
        system_instruction=system_prompt,
        temperature=temperature,
        tools=tools_config,
    )
    if AGENTIC_THINKING_BUDGET is not None:
        _cfg_kwargs["thinking_config"] = genai_types.ThinkingConfig(
            thinking_budget=int(AGENTIC_THINKING_BUDGET)
        )
    # Track 6 (2026-08-22, doc oficial function-calling): VALIDATED = constrained
    # decoding de function calls — elimina args malformados POR CONSTRUCCIÓN
    # (hoy MALFORMED_FUNCTION_CALL se trata con retry: síntoma, no causa).
    # Flag env para canary STG (medir latencia/calidad antes de volverlo default).
    if tools_config and os.getenv("AGENTIC_TOOL_VALIDATED_ENABLED", "false").lower() == "true":
        _cfg_kwargs["tool_config"] = genai_types.ToolConfig(
            function_calling_config=genai_types.FunctionCallingConfig(
                mode=genai_types.FunctionCallingConfigMode.VALIDATED
            )
        )
    config = genai_types.GenerateContentConfig(**_cfg_kwargs)

    def _invoke_with_model(model_name: str):
        """Closure que `generate_with_cascade` invoca por modelo."""
        return client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )

    import asyncio
    loop = asyncio.get_running_loop()
    cascade_result = await loop.run_in_executor(
        None,
        lambda: generate_with_cascade(
            _invoke_with_model,
            primary_model=model,
        ),
    )

    if cascade_result.degraded:
        # Cascada agotada (primary + fallback 503 sostenido o deadline
        # agotado). Raise para que el caller del loop convierta en error →
        # dispatcher responde degraded + escala (V1 legacy retirado, K-2).
        raise RuntimeError(
            f"gemini_cascade_exhausted after {cascade_result.attempts} attempts: "
            f"{cascade_result.last_error or 'unknown'}"
        )

    logger.info(
        "[AGENTIC_CASCADE] model_used=%s attempts=%d",
        cascade_result.model_used, cascade_result.attempts,
    )
    return cascade_result.response


def _part_from_dict(part_dict: dict):
    """Convierte dict-style part a Gemini Part."""
    from google.genai import types as genai_types
    if "text" in part_dict:
        return genai_types.Part(text=part_dict["text"])
    if "function_call" in part_dict:
        fc = part_dict["function_call"]
        return genai_types.Part(
            function_call=genai_types.FunctionCall(name=fc["name"], args=fc["args"]),
            # Gemini 3.x: reinyectar la firma capturada del response del modelo,
            # requisito para que el tool-call multi-turno sea aceptado por la API.
            thought_signature=part_dict.get("thought_signature"),
        )
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
                    # Gemini 3.x: la firma del pensamiento viaja en el Part (no en
                    # el FunctionCall) y DEBE reenviarse en el turno siguiente del
                    # loop de tools, o la API rechaza con 400 INVALID_ARGUMENT
                    # ("missing a thought_signature"). Gemini 2.5 no la exigía.
                    "thought_signature": getattr(part, "thought_signature", None),
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


def _extract_total_tokens(response: Any) -> int:
    """Extrae `usage_metadata.total_token_count` del response Gemini.

    F5 telemetría de costo (decisión bot_engine #2). Best-effort: si el SDK
    no reporta usage (response degraded, mock de test sin usage_metadata),
    retorna 0 — NUNCA rompe el turn. Suma prompt + candidates + tool tokens
    (total_token_count ya los engloba en el SDK google-genai).
    """
    return _extract_usage(response)["total_tokens"]


def _extract_usage(response: Any) -> dict:
    """Track 6 (2026-08-22): breakdown de usage_metadata para medir caching.

    La auditoría del bot asumió el ahorro por context caching; la doc oficial
    NO garantiza implicit caching para flash-lite (la tabla de mínimos omite
    los Lite). Fase 0 = medir: cached_content_token_count > 0 sostenido sería
    la evidencia de que el prefijo estable está pegando. Best-effort igual que
    `_extract_total_tokens`: ceros si el SDK no reporta.
    """
    base = {"total_tokens": 0, "prompt_tokens": 0, "cached_tokens": 0, "thoughts_tokens": 0}
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return base
        for key, attr in (
            ("total_tokens", "total_token_count"),
            ("prompt_tokens", "prompt_token_count"),
            ("cached_tokens", "cached_content_token_count"),
            ("thoughts_tokens", "thoughts_token_count"),
        ):
            val = getattr(usage, attr, None)
            base[key] = int(val) if val else 0
        return base
    except Exception:
        return base


def _extract_finish_reason(response: Any) -> str:
    """Extrae el `finish_reason` del primer candidate del response.

    Valores típicos Gemini: 'STOP', 'MAX_TOKENS', 'SAFETY', 'RECITATION',
    'OTHER', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'MALFORMED_FUNCTION_CALL'.
    Retorna '' si no se puede determinar.
    """
    if not response or not response.candidates:
        return ""
    candidate = response.candidates[0]
    fr = getattr(candidate, "finish_reason", None)
    if fr is None:
        return ""
    # `finish_reason` puede ser enum o int — normalizar a string.
    name = getattr(fr, "name", None)
    if name:
        return str(name).upper()
    return str(fr).upper()


# Strategies de recovery para empty_output según finish_reason.
# Cada strategy retorna (outbound_text, should_retry, retry_history_limit).
# Si should_retry=True, el caller re-invoca Gemini con history limitado.
# Si False, retorna outbound_text directo como degraded response al cliente.

def _recovery_strategy_for_finish_reason(
    finish_reason: str,
    attempt: int,
) -> tuple[str, bool, int]:
    """Decide cómo recuperar de un empty_output según finish_reason.

    Args:
        finish_reason: valor canónico Gemini (e.g. 'MAX_TOKENS', 'SAFETY').
        attempt: 0 = primer empty_output, 1+ = post-retry.

    Returns:
        (outbound_text, should_retry, retry_history_limit)
        • should_retry=True → el caller invoca Gemini de nuevo con
          history limitado a `retry_history_limit` (0 = todo).
        • outbound_text = mensaje degraded determinístico al cliente
          si la strategy decide no reintentar (o ya agotó retry).
    """
    # Solo 1 retry por turn — evita loops infinitos.
    can_retry = attempt < 1

    if finish_reason == "MAX_TOKENS" and can_retry:
        # Response truncada — retry con history reducido a últimos 5 turns.
        return ("", True, 5)

    if finish_reason == "RECITATION" and can_retry:
        # Detectó copia literal del catalog — retry sin tools para forzar
        # respuesta paraphraseada por el LLM en lugar de tool-call.
        return ("", True, 10)

    if finish_reason == "SAFETY":
        # Bloqueado por filtros de seguridad. NO retry — mismo input
        # produce mismo bloqueo.
        return (DEGRADED_SAFETY, False, 0)

    if finish_reason in ("BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
        # Contenido bloqueado por políticas Gemini.
        return (DEGRADED_BLOCKLIST, False, 0)

    if finish_reason == "MALFORMED_FUNCTION_CALL" and can_retry:
        # El LLM generó tool call con args inválidos. Retry forzando
        # respuesta textual (history reducido para evitar repetir patrón).
        return ("", True, 5)

    # STOP con parts vacío: Gemini cerró el response sin emitir texto ni
    # function_call. Causa raíz observada (conv KAIU bde83d84 y phone
    # 573999999999 turno 2): system_prompt+history saturados con
    # ≥16 tools registrados → el modelo "renuncia" sin payload.
    # Estrategia rev. 107: 1 retry con history reducido a los últimos
    # 5 turns (suficiente contexto para respuesta natural sin saturar).
    # Si tras retry sigue empty, ahí sí degraded.
    if finish_reason == "STOP" and can_retry:
        return ("", True, 5)

    # OTHER / UNKNOWN — sin más info, degraded inmediato.
    return (DEGRADED_GENERIC, False, 0)


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
