"""Escalación silenciosa ante BLOCK de invariant (B-0 F4, 2026-08-21).

Antes de este fix: un BLOCK del pipeline de invariants (guard de
dinero/verdad CAÍDO — fail-closed A4 — o intervención de dinero) servía al
cliente `DEGRADED_GENERIC` ("Déjame revisar bien tu solicitud con mi
equipo. Te respondo en un momento…") pero NADIE era notificado — el
cliente quedaba esperando un seguimiento que no existía ("bot mudo" con
promesa implícita de humano).

Este helper materializa la escalación, reusando el patrón canónico ya
existente (`_emit_degraded_response_and_escalate` + bloque
`requires_silent_escalation` del dispatcher + `_escalate_conversation_to_human`):
  1. Throttle 10 min por conversación (audit `escalation_audit` con
     `payload.source='invariant_block'`): si ya hubo escalación de esta
     fuente en la ventana, NO duplica status/audit/Telegram.
  2. `conversations.status = human_takeover` — el operador toma el control.
  3. Audit append-only en `messages` (alimenta el throttle de futuros
     BLOCKs y deja traza del invariant que intervino).
  4. Notificación Telegram al operador (severity critical).

Todo best-effort: ni el audit ni la notificación bloquean; el cambio de
status es lo crítico, y si el chequeo del throttle falla se escala igual
(mejor una notificación duplicada que un cliente sin seguimiento).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Ventana anti-duplicados por conversación — misma ventana de 10 min que
# usa `_emit_degraded_response_and_escalate` para su conteo de fallos.
_ESCALATION_THROTTLE_MINUTES = 10


async def escalate_invariant_block(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    invariant_name: str,
    reason: str,
) -> bool:
    """Escala a operador un BLOCK de invariant. True si escaló, False si throttle.

    Args:
        supabase: cliente DB.
        tenant_id: scope multi-tenant (todos los queries/updates filtrados).
        conversation_id: conversación a pausar (human_takeover).
        invariant_name: invariant que devolvió BLOCK (traza).
        reason: razón del BLOCK (truncada en audit/notificación).
    """
    # 1. Throttle: ¿ya hubo escalación 'invariant_block' en los últimos
    #    10 min para esta conversación? El audit se filtra en Python (el
    #    payload es jsonb) — simple y sin depender de sintaxis `payload->>`.
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=_ESCALATION_THROTTLE_MINUTES)
    ).isoformat()
    try:
        rows = (
            supabase.table("messages")
            .select("payload")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)  # A6.2.7: defensa cross-tenant
            .eq("content_type", "escalation_audit")
            .gte("created_at", since)
            .limit(10)
            .execute()
        )
        for row in (rows.data or []):
            if (row.get("payload") or {}).get("source") == "invariant_block":
                logger.info(
                    "[INVARIANT_BLOCK] throttle %d min: conv=%s ya escalada "
                    "— no duplicar (invariant=%s)",
                    _ESCALATION_THROTTLE_MINUTES,
                    conversation_id[:8], invariant_name,
                )
                return False
    except Exception as exc:
        logger.warning(
            "[INVARIANT_BLOCK] throttle check falló conv=%s: %s — "
            "escalando igual (mejor duplicar que no escalar)",
            conversation_id[:8], exc,
        )

    # 2. Pausar la conversación: operador humano toma el control.
    try:
        supabase.table("conversations").update({
            "status": "human_takeover",
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.warning(
            "[INVARIANT_BLOCK] conv=%s no pude marcar human_takeover: %s — "
            "sigo con audit + notificación",
            conversation_id[:8], exc,
        )

    # 3. Audit append-only (alimenta el throttle de futuros BLOCKs).
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "escalation_audit",
            "content": "",
            "payload": {
                "source": "invariant_block",
                "invariant": invariant_name,
                "reason": (reason or "")[:300],
            },
            "processed": True,
            "processing_status": "processed",
        }).execute()
    except Exception:
        pass

    # 4. Notificar al operador (mismo canal que silent_escalation / menor /
    #    handoff del router). Best-effort.
    try:
        from telegram_notifications import notify_escalation_async
        await notify_escalation_async(
            supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reason=(
                f"🚨 *Guard de dinero/verdad bloqueó una respuesta*\n"
                f"Invariant `{invariant_name}` devolvió BLOCK — el cliente "
                f"recibió mensaje neutro y espera seguimiento.\n\n"
                f"Motivo: `{(reason or '')[:200]}`\n\n"
                f"Conversación pasó a human_takeover. Acción: revisar el "
                f"último outbound candidato y responder al cliente."
            ),
            severity="critical",
        )
    except Exception as exc:
        logger.warning("[INVARIANT_BLOCK] telegram notif falló: %s", exc)

    logger.info(
        "[INVARIANT_BLOCK] conv=%s invariant=%s → human_takeover + operador "
        "notificado",
        conversation_id[:8], invariant_name,
    )
    return True
