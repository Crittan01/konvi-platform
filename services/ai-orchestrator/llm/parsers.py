"""Parsers de respuesta Gemini → dataclasses tipados.

Aísla a los specialists del SDK ``google-genai`` y de la estructura de
``response.candidates[0].content.parts[]``.

Referencias oficiales:
  - FinishReason enum: https://ai.google.dev/api/generate-content
  - Function Calling response format:
    https://ai.google.dev/gemini-api/docs/function-calling
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FinishReason(str, Enum):
    """Subset de ``finishReason`` documentado por Google AI.

    Mapeo a acciones del orquestador en :func:`map_finish_reason_to_action`.
    """

    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"
    RECITATION = "RECITATION"
    LANGUAGE = "LANGUAGE"
    OTHER = "OTHER"
    BLOCKLIST = "BLOCKLIST"
    PROHIBITED_CONTENT = "PROHIBITED_CONTENT"
    SPII = "SPII"
    MALFORMED_FUNCTION_CALL = "MALFORMED_FUNCTION_CALL"
    IMAGE_SAFETY = "IMAGE_SAFETY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, raw: Optional[str]) -> "FinishReason":
        if not raw:
            return cls.UNKNOWN
        try:
            return cls(raw.upper())
        except ValueError:
            return cls.UNKNOWN


class FinishAction(str, Enum):
    """Decisión derivada de ``FinishReason`` para el orquestador."""

    OK = "ok"
    RETRY = "retry"
    HUMAN_HANDOFF = "human_handoff"
    DEGRADE = "degrade"


def map_finish_reason_to_action(reason: FinishReason) -> FinishAction:
    """Política mínima documentada en spec del agente Gemini."""
    if reason == FinishReason.STOP:
        return FinishAction.OK
    if reason in {FinishReason.MAX_TOKENS, FinishReason.OTHER, FinishReason.UNKNOWN}:
        return FinishAction.RETRY
    if reason in {
        FinishReason.SAFETY,
        FinishReason.BLOCKLIST,
        FinishReason.PROHIBITED_CONTENT,
        FinishReason.SPII,
        FinishReason.IMAGE_SAFETY,
    }:
        return FinishAction.HUMAN_HANDOFF
    if reason == FinishReason.MALFORMED_FUNCTION_CALL:
        # Reintentar con mode=VALIDATED si se soporta; degradar a texto si no.
        return FinishAction.RETRY
    return FinishAction.DEGRADE


@dataclass
class FunctionCall:
    """Una invocación de tool emitida por el modelo.

    Coincide con ``content.parts[i].function_call.{name, args, id}`` del SDK.
    """

    name: str
    args: dict
    call_id: Optional[str] = None


@dataclass
class LlmTurn:
    """Resultado de una llamada al LLM.

    Convención:
      - Si ``function_calls`` no está vacío, el coordinator debe ejecutar las
        tools y eventualmente re-invocar con los resultados (``function_response``).
      - Si ``text`` no es None, es texto natural listo para enviar al cliente.
      - ``function_calls`` y ``text`` pueden coexistir (modelo puede pedir
        tools y agregar comentario; lo manejamos como "ejecutar tools primero,
        ignorar texto" salvo que `finish_reason=STOP`).
      - ``finish_reason`` y ``finish_action`` siempre presentes.
    """

    text: Optional[str]
    function_calls: list[FunctionCall] = field(default_factory=list)
    finish_reason: FinishReason = FinishReason.UNKNOWN
    finish_action: FinishAction = FinishAction.OK
    raw_response: Any = None  # útil para debugging, no para dependencias


def parse_response(response: Any) -> LlmTurn:
    """Convierte un ``GenerateContentResponse`` (SDK ``google-genai``) a
    :class:`LlmTurn`.

    Tolerante a respuestas malformadas: si no hay ``candidates``, retorna
    un turn vacío con ``finish_reason=UNKNOWN``.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return LlmTurn(
            text=None,
            finish_reason=FinishReason.UNKNOWN,
            finish_action=FinishAction.RETRY,
            raw_response=response,
        )

    cand = candidates[0]
    fr_raw = getattr(cand, "finish_reason", None)
    # SDK puede devolver enum o string
    fr = FinishReason.from_str(fr_raw.name if hasattr(fr_raw, "name") else fr_raw)

    parts = []
    content = getattr(cand, "content", None)
    if content is not None:
        parts = getattr(content, "parts", None) or []

    text_buf: list[str] = []
    fcalls: list[FunctionCall] = []
    for part in parts:
        # function_call
        fc = getattr(part, "function_call", None)
        if fc:
            args = getattr(fc, "args", None) or {}
            # SDK retorna args como dict-like; normalizamos a dict puro
            if not isinstance(args, dict):
                try:
                    args = dict(args)
                except Exception:
                    args = {}
            fcalls.append(
                FunctionCall(
                    name=str(getattr(fc, "name", "") or ""),
                    args=args,
                    call_id=getattr(fc, "id", None),
                )
            )
            continue
        # text
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            text_buf.append(text)

    return LlmTurn(
        text="".join(text_buf) or None,
        function_calls=fcalls,
        finish_reason=fr,
        finish_action=map_finish_reason_to_action(fr),
        raw_response=response,
    )
