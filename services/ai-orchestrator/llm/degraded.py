"""LLM degraded path — handoff humano vía review_queue (rev. 104, F1-10).

Antes: cuando `generate_with_cascade` agotaba reintentos, el orchestrator
emitía un texto genérico ("tuve un problema técnico") y dejaba al cliente
en limbo. El operador humano NO veía qué falló ni en qué punto.

Ahora: `on_cascade_degraded` encola una entrada en `review_queue` con:
  • `reason='llm_degraded'`
  • `error_chain` (excepción) + `prompt_snapshot` (truncado para audit)
  • `fsm_state` al momento del fallo
  • `priority` (1 normal · 2 alta · 3 crítica)

El operador ve la cola en la UI Inbox / "Revisión LLM" y atiende. Cuando
resuelve, marca `resolved=true` con nota.

Mantenemos el comportamiento legacy de respuesta al cliente
(`degraded_response_text`) — el cambio es de telemetría + handoff, no
visible al cliente excepto que el operador puede tomar la conversación
con contexto completo.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def enqueue_review_queue(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    reason: str,
    last_message_id: Optional[str] = None,
    fsm_state: Optional[str] = None,
    error_chain: Optional[str] = None,
    prompt_snapshot: Optional[str] = None,
    priority: int = 1,
) -> Optional[str]:
    """Inserta una fila en review_queue. Best-effort — no bloquea si falla.

    Args:
        supabase: cliente con service_role (escribe ignorando RLS).
        tenant_id, conversation_id: contexto.
        reason: 'llm_degraded' | 'invariant_block' | 'manual_escalation'.
        last_message_id: mensaje que disparó (para deeplink).
        fsm_state: estado al momento del fallo.
        error_chain, prompt_snapshot: telemetría para el operador.
        priority: 1 normal · 2 alta · 3 crítica.

    Returns:
        id de la fila insertada, o None si falló.
    """
    try:
        # Truncamos prompt_snapshot a 8KB para no inflar la tabla.
        snap = (prompt_snapshot or "")[:8000] if prompt_snapshot else None
        err = (error_chain or "")[:2000] if error_chain else None
        res = supabase.table("review_queue").insert({
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "last_message_id": last_message_id,
            "fsm_state": fsm_state,
            "reason": reason,
            "error_chain": err,
            "prompt_snapshot": snap,
            "priority": priority,
        }).execute()
        row_id = (res.data or [{}])[0].get("id") if res.data else None
        logger.info(
            "[REVIEW_QUEUE] enqueued conv=%s reason=%s priority=%d row=%s",
            conversation_id[:8] if conversation_id else "?",
            reason, priority,
            (row_id[:8] if row_id else "?"),
        )
        return row_id
    except Exception as exc:
        # No bloqueante — el cliente ya recibirá el degraded response;
        # no perdemos el handoff (status=human_takeover). Solo perdemos
        # la pista en review_queue para el operador.
        logger.error(
            "[REVIEW_QUEUE] enqueue falló conv=%s reason=%s: %s",
            conversation_id, reason, exc,
        )
        return None


def on_cascade_degraded(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    last_message_id: Optional[str],
    fsm_state: Optional[str],
    error: Optional[str],
    prompt_snapshot: Optional[str],
) -> None:
    """Hook a invocar cuando `generate_with_cascade` retorna `degraded=True`.

    Encola en review_queue + cambia status conversación a `human_takeover`
    para que futuros inbounds del cliente NO vuelvan a entrar al LLM.
    """
    enqueue_review_queue(
        supabase,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason="llm_degraded",
        last_message_id=last_message_id,
        fsm_state=fsm_state,
        error_chain=error,
        prompt_snapshot=prompt_snapshot,
        priority=2,  # alta — el cliente vio respuesta degradada
    )
    # Cambiar status a human_takeover.
    try:
        supabase.table("conversations").update({
            "status": "human_takeover",
        }).eq("tenant_id", tenant_id).eq("id", conversation_id).execute()
        logger.info(
            "[DEGRADED_HANDOFF] conv=%s → human_takeover",
            conversation_id[:8],
        )
    except Exception as exc:
        logger.warning(
            "[DEGRADED_HANDOFF] no pude cambiar status conv=%s: %s",
            conversation_id, exc,
        )
