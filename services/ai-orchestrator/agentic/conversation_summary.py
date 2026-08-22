"""B-1 — Resumen rodante de conversación (memoria fuera de ventana).

Auditoría bot 2026-08-21 (amnesia estructural): la ventana de 25 mensajes es
TODO lo que el LLM ve — lo hablado antes desaparece del contexto ("el bot
olvida"). Este módulo mantiene un resumen rodante en
`conversations.conversation_summary` y lo inyecta como primer content de la
ventana Gemini (NUNCA en el system prompt: preserva el prefijo estable de
implicit caching — decisión Track 6).

Diseño (resumen FUERA-de-ventana, no reducción de ventana):
  • La ventana cruda de 25 mensajes se mantiene intacta — varios componentes
    determinísticos la leen (affirmation, guards de add_to_cart, state resolver).
  • Trigger con histeresis: la conv tiene >CONVERSATION_HISTORY_LIMIT mensajes
    Y >=SUMMARY_REGEN_MIN_NEW mensajes nuevos desde `covers_until_created_at`.
  • El resumidor es flash-lite a temperatura 0 con instrucción explícita de
    OMITIR montos/estados transaccionales: la verdad de dinero sale de los
    bloques determinísticos del carrito (ADR-0026) y los invariants validan
    contra DB — un monto viejo en el resumen sería riesgo innecesario.
  • Cursor append-only (`covers_until_created_at`): no hay invalidación
    semántica — cada regeneración cubre hasta el borde actual de la ventana.

Todo es best-effort: ningún fallo rompe el turno.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mensajes nuevos mínimos desde el último resumen para regenerar (histeresis).
SUMMARY_REGEN_MIN_NEW = int(os.getenv("SUMMARY_REGEN_MIN_NEW", "10"))
# Tope de mensajes a plegar por regeneración (defensa de costo/latencia).
_SUMMARY_MAX_FOLD = 60
# Tope del texto del resumen que se inyecta al prompt (defensa de tokens).
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "900"))

# Prefijo del bloque sintético en la ventana Gemini — el retry por
# empty_output lo reconoce para PRESERVARLO al recortar la historia.
SUMMARY_PROMPT_PREFIX = (
    "[Contexto de la conversación anterior — resumen automático]"
)

_SUMMARIZER_INSTRUCTION = """Eres el compactador de memoria de un bot de ventas por WhatsApp (Colombia).
Actualiza el resumen de la conversación para que el bot recuerde lo esencial
fuera de su ventana de mensajes recientes.

REGLAS:
- Español, máximo 120 palabras, viñetas cortas y concretas.
- CONSERVA: nombre/datos personales que el cliente dio, productos pedidos con
  cantidades y variantes, ciudad/dirección de envío, carrier elegido, modo de
  pago elegido, cupón aplicado, acuerdos ya hechos, en qué paso va el trámite,
  dudas pendientes del cliente.
- NO copies montos ni totales en pesos: la verdad de dinero sale SIEMPRE del
  carrito en la base de datos, no de este resumen. Si importa, di "el total ya
  fue calculado/actualizado" sin la cifra.
- NO inventes nada que no esté en los mensajes.
- Si el resumen anterior dice algo que los mensajes nuevos contradicen
  (cambió el pedido, cambió la ciudad…), gana lo nuevo."""


def summary_text_for_prompt(summary_row: Optional[dict]) -> Optional[str]:
    """Extrae el texto inyectable del JSONB (o None si no hay resumen útil)."""
    if not isinstance(summary_row, dict):
        return None
    text = str(summary_row.get("text") or "").strip()
    if not text:
        return None
    return text[:SUMMARY_MAX_CHARS]


def is_summary_message(msg: dict) -> bool:
    """True si el mensaje Gemini es el bloque sintético de resumen (prefijo)."""
    try:
        parts = msg.get("parts") or []
        text = str((parts[0] or {}).get("text") or "")
        return text.startswith(SUMMARY_PROMPT_PREFIX)
    except Exception:
        return False


def build_summary_message(text: str) -> dict:
    """El content sintético que abre la ventana Gemini (role user)."""
    return {
        "role": "user",
        "parts": [{
            "text": (
                f"{SUMMARY_PROMPT_PREFIX}\n{text}\n"
                "[Fin del resumen — los mensajes siguientes son los más recientes]"
            ),
        }],
    }


def _render_messages_for_summary(rows: list[dict]) -> str:
    """Render compacto de los mensajes a plegar (truncado por mensaje)."""
    lines = []
    for r in rows:
        direction = "Cliente" if str(r.get("direction") or "") == "inbound" else "Bot"
        content = str(r.get("content") or "").strip().replace("\n", " ")
        if content:
            lines.append(f"{direction}: {content[:280]}")
    return "\n".join(lines)


async def _summarize_with_llm(
    *,
    prev_text: str,
    new_rows: list[dict],
) -> Optional[str]:
    """Una llamada barata (flash-lite, temp 0) al resumidor. None si falla."""
    try:
        from google import genai
        from google.genai import types as genai_types
        from agentic.agent import _get_genai_client

        client = _get_genai_client(genai, genai_types)
        model = os.getenv("AGENTIC_MODEL", "gemini-3.1-flash-lite")
        user_content = (
            f"[Resumen anterior]\n{prev_text or '(vacío — primer resumen)'}\n\n"
            f"[Mensajes a incorporar]\n{_render_messages_for_summary(new_rows)}"
        )
        response = client.models.generate_content(
            model=model,
            contents=user_content,
            config=genai_types.GenerateContentConfig(
                system_instruction=_SUMMARIZER_INSTRUCTION,
                temperature=0.0,
            ),
        )
        text = (getattr(response, "text", None) or "").strip()
        return text or None
    except Exception as exc:
        logger.info("[SUMMARY] resumidor LLM falló (best-effort): %s", exc)
        return None


async def maybe_update_conversation_summary(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    history_limit: int = 25,
) -> None:
    """Regenera el resumen rodante si la conversación lo amerita (histeresis).

    Se invoca post-turn (fire-and-forget). Nunca lanza.
    """
    try:
        # 1. Estado actual del resumen.
        conv_res = (
            supabase.table("conversations")
            .select("conversation_summary")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        conv = (getattr(conv_res, "data", None) or [{}])[0]
        current = conv.get("conversation_summary")
        if not isinstance(current, dict):
            current = {}
        covers_until = str(current.get("covers_until_created_at") or "")
        prev_text = str(current.get("text") or "")

        # 2. ¿La conv supera la ventana? (sin ella no hay nada que resumir)
        count_res = (
            supabase.table("messages")
            .select("id", count="exact", head=True)
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        total = int(getattr(count_res, "count", 0) or 0)
        if total <= history_limit:
            return

        # 3. Borde de la ventana: created_at del mensaje #history_limit más
        #    reciente (los anteriores a él son los que salen de la ventana).
        edge_res = (
            supabase.table("messages")
            .select("created_at")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .range(history_limit - 1, history_limit - 1)
            .execute()
        )
        edge_row = (getattr(edge_res, "data", None) or [None])[0]
        edge = str((edge_row or {}).get("created_at") or "")
        if not edge:
            return

        # 4. Histeresis: mensajes nuevos a plegar desde covers_until.
        fold_q = (
            supabase.table("messages")
            .select("direction, content, created_at")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .lt("created_at", edge)
            .order("created_at", desc=False)
        )
        if covers_until:
            fold_q = fold_q.gt("created_at", covers_until)
        fold_res = fold_q.limit(_SUMMARY_MAX_FOLD).execute()
        fold_rows = getattr(fold_res, "data", None) or []
        if covers_until and len(fold_rows) < SUMMARY_REGEN_MIN_NEW:
            return
        if not fold_rows:
            return

        # 5. Resumir (prev + nuevos) y persistir (best-effort).
        new_text = await _summarize_with_llm(prev_text=prev_text, new_rows=fold_rows)
        if not new_text:
            return
        supabase.table("conversations").update({
            "conversation_summary": {
                "text": new_text[:SUMMARY_MAX_CHARS],
                "covers_until_created_at": edge,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "message_count": total,
            },
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
        logger.info(
            "[SUMMARY] resumen rodante actualizado conv=%s (%d msgs plegados, "
            "covers=%s)",
            conversation_id[:8], len(fold_rows), edge[:19],
        )
    except Exception as exc:  # noqa: BLE001 — NUNCA rompe el turno
        logger.info(
            "[SUMMARY] update falló conv=%s: %s (best-effort)",
            conversation_id[:8], exc,
        )


async def fetch_summary_text(
    supabase: Any, *, tenant_id: str, conversation_id: str,
) -> Optional[str]:
    """Lee el texto del resumen para inyectarlo al turno (None si no hay)."""
    try:
        res = (
            supabase.table("conversations")
            .select("conversation_summary")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        row = (getattr(res, "data", None) or [{}])[0]
        return summary_text_for_prompt(row.get("conversation_summary"))
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "[SUMMARY] fetch falló conv=%s: %s — turno sin resumen",
            conversation_id[:8], exc,
        )
        return None
