"""Notificaciones Telegram a operador del tenant (escalations).

Rev. 109 producción — usado por dispatcher.py + agentic/tools/escalation.py
para alertar al operador humano cuando el bot decide escalar (cancelación
requiere refund manual, sentiment hostil, alto monto, etc.).

Diseño:
  • Lee `tenant_integrations.meta.telegram_chat_id` del tenant.
  • POST a Bot API oficial (`https://api.telegram.org/bot{token}/sendMessage`).
  • Reusa `_send_telegram_notification` de notifications.py para no duplicar
    el cliente HTTP + parsing de credenciales.
  • Append-only audit en `telegram_notifications_log` (si la tabla existe).

NO duplica lógica de notifications.py — extiende con un wrapper específico
para escalaciones de cancel/refund que recibe (tenant_id, conv_id, reason).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("orchestrator.telegram_notifications")


async def notify_escalation_async(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: Optional[str] = None,
    reason: str = "",
    severity: str = "warning",
) -> bool:
    """Envía notif Telegram al operador del tenant.

    Args:
        supabase: cliente DB.
        tenant_id: para resolver bot_token + chat_id del tenant.
        conversation_id: contexto opcional (incluido en el mensaje).
        reason: texto descriptivo de la escalación (multilinea OK).
        severity: 'info' | 'warning' | 'critical' (afecta emoji prefijo).

    Returns:
        True si Telegram aceptó el mensaje, False si fallo (creds ausentes,
        chat_id sin configurar, error HTTP, etc.).
    """
    if not reason:
        return False

    # Resolver chat_id + bot_token del tenant.
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "telegram")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.info(
            "[TG_ESCALATION] tenant=%s sin integración telegram conectada: %s",
            tenant_id, exc,
        )
        return False

    if not res or not getattr(res, "data", None):
        return False

    meta = (res.data.get("meta") or {})
    chat_id = meta.get("chat_id") or meta.get("telegram_chat_id")
    if not chat_id:
        logger.info(
            "[TG_ESCALATION] tenant=%s sin chat_id configurado", tenant_id,
        )
        return False

    creds = (res.data.get("credentials") or {})
    try:
        from vault_helper import VaultHelper, resolve_secret
        vault = VaultHelper(supabase)
        bot_token = resolve_secret(vault, creds, "bot_token")
    except Exception as exc:
        logger.warning(
            "[TG_ESCALATION] tenant=%s no pudo resolver bot_token: %s",
            tenant_id, exc,
        )
        return False
    if not bot_token:
        return False

    prefix = {
        "info": "ℹ️", "warning": "⚠️", "critical": "🚨",
    }.get(severity, "⚠️")
    convo_suffix = (
        f"\n\n_Conv: {conversation_id[:8]}_" if conversation_id else ""
    )
    text = f"{prefix} *Escalación*\n\n{reason}{convo_suffix}"

    config = {"telegram_bot_token": bot_token, "telegram_chat_id": chat_id}
    try:
        from notifications import _send_telegram_notification
        return await _send_telegram_notification(config, text)
    except Exception as exc:
        logger.warning(
            "[TG_ESCALATION] send falló tenant=%s: %s", tenant_id, exc,
        )
        return False
