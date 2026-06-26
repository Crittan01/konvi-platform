"""Helper compartido para features "Sugerir con IA" (catálogo, settings, etc.).

Encapsula el cliente Gemini + cascade + config (molde extraído de
routers/ai_agents.py). Cada feature aporta su META-PROMPT y su GROUNDING
propios — el grounding y las reglas anti-claims NO viven aquí porque varían por
superficie (producto cara-al-consumidor = Ley 1480 estricto; KB = verdad
transaccional; etc.). Este helper solo hace la invocación robusta.

Human-in-the-loop: el helper SOLO genera texto/JSON. NUNCA persiste. El caller
retorna un draft que el merchant revisa/edita/guarda explícitamente.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Tiers canónicos (barato → caro), igual que ai_agents.py.
_TIERS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


@dataclass
class SuggestionResult:
    text: str                 # texto crudo del LLM (o "")
    data: Optional[dict]      # JSON parseado si json_mode y parse OK
    model_used: Optional[str]
    degraded: bool            # True si Gemini falló / saturó / JSON inválido


def run_suggestion(
    meta_prompt: str,
    *,
    max_output_tokens: int = 800,
    temperature: float = 0.4,
    json_mode: bool = False,
) -> SuggestionResult:
    """Invoca Gemini con cascade. `temperature` baja (0.4) = más conservador
    que el 0.5 de agentes (contenido de producto debe ser menos creativo).
    `json_mode` pide response_mime_type=application/json y parsea. Nunca lanza:
    ante cualquier fallo retorna degraded=True con text="" / data=None."""
    text = ""
    data: Optional[dict] = None
    model_used: Optional[str] = None
    degraded = True
    try:
        from google.genai import types as genai_types
        from llm_cascade import cascade_invoke
        from orchestrator import _get_genai_client

        client = _get_genai_client()

        def _invoke(model_name: str):
            cfg = {
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                # Gemini 2.5: max_output_tokens cuenta thinking + salida. Para
                # generación de contenido (no razonamiento) desactivar thinking
                # evita que se coma el presupuesto y trunque el JSON a medias.
                # (flash/flash-lite aceptan budget=0; si el cascade llega a pro,
                # que requiere thinking, esa llamada degrada y no rompe.)
                "thinking_config": genai_types.ThinkingConfig(thinking_budget=0),
            }
            if json_mode:
                cfg["response_mime_type"] = "application/json"
            return client.models.generate_content(
                model=model_name,
                contents=meta_prompt,
                config=genai_types.GenerateContentConfig(**cfg),
            )

        outcome = cascade_invoke(
            gemini_invoker=_invoke,
            tiers=_TIERS,
            attempts_per_tier=2,
        )
        if not outcome.degraded and outcome.response is not None:
            text = (getattr(outcome.response, "text", "") or "").strip()
            model_used = outcome.model_used
            degraded = False
            if json_mode and text:
                try:
                    parsed = json.loads(text)
                    data = parsed if isinstance(parsed, dict) else None
                    if data is None:
                        degraded = True  # JSON no-objeto → tratar como fallo
                except Exception:
                    data = None
                    degraded = True  # JSON inválido → fallback del caller
    except Exception as exc:
        logger.warning("[LLM_SUGGEST] cascade falló: %s", exc)
    return SuggestionResult(
        text=text, data=data, model_used=model_used, degraded=degraded,
    )
