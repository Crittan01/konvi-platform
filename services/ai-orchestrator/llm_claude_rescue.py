"""Claude rescue invoker (rev. 109 Día 3).

Cuando los 3 tiers Gemini fallan, invocamos Claude Sonnet para generar
una respuesta texto-only (sin tool calling) que NO deje al cliente con
mensaje degraded.

Diseño:
  • Text-only — Claude no maneja tools en este tier. Es resilience cross-
    vendor para mantener UX, no para completar el flujo agentic.
  • Mismo system_prompt que Gemini. El prompt ya contiene reglas de
    seguridad + identidad — Claude las respeta.
  • Si falla, retorna degraded (mismo path del legacy cascade).

ENV:
  ANTHROPIC_API_KEY — required. Sin esta key, cascade omite el tier
    Claude (skipped silenciosamente — ver llm_cascade.py).
  ANTHROPIC_MODEL   — override del default "claude-sonnet-4-5".
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("orchestrator.llm.claude_rescue")


_DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 1024


@dataclass
class ClaudeRescueResponse:
    """Respuesta normalizada del Claude rescue."""
    text: str
    model: str
    stop_reason: Optional[str] = None


def is_available() -> bool:
    """True si Claude rescue puede invocarse (key presente + SDK importable)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        logger.warning(
            "[CLAUDE_RESCUE] anthropic SDK no instalado — pip install anthropic",
        )
        return False


def invoke_claude_text_only(
    *,
    system_prompt: str,
    user_text: str,
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    max_tokens: int = _MAX_TOKENS,
) -> ClaudeRescueResponse:
    """Invoca Claude para generar respuesta texto-only.

    Args:
      system_prompt: mismo prompt que se usa con Gemini.
      user_text: mensaje del cliente.
      history: lista opcional de turns previos [{role, content}].
      model: override del default claude-sonnet-4-5.
      max_tokens: límite de tokens (default 1024 — respuestas WhatsApp).

    Returns:
      ClaudeRescueResponse con texto generado.

    Raises:
      ImportError si anthropic SDK no instalado.
      RuntimeError si API key falta.
      anthropic.APIError si la llamada falla.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada")

    model_name = model or os.getenv("ANTHROPIC_MODEL", _DEFAULT_CLAUDE_MODEL)
    client = anthropic.Anthropic(api_key=api_key)

    # Normalizar history a formato Anthropic.
    messages: list[dict] = []
    for turn in history or []:
        role = turn.get("role") or "user"
        # Anthropic acepta 'user' | 'assistant'. Mapear 'model' → 'assistant'.
        if role == "model":
            role = "assistant"
        content = turn.get("content") or turn.get("text") or ""
        if isinstance(content, list):
            # Lista de parts — extraer solo texto.
            content = "\n".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            ).strip()
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})

    response = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )

    # Extraer texto del primer content block.
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
        elif isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")

    logger.info(
        "[CLAUDE_RESCUE] model=%s stop_reason=%s text_len=%d",
        model_name, getattr(response, "stop_reason", None), len(text),
    )

    return ClaudeRescueResponse(
        text=text.strip(),
        model=model_name,
        stop_reason=getattr(response, "stop_reason", None),
    )
