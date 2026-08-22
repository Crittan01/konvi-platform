"""Alertas operativas al operador del tenant vía Telegram, desde el API service.

B4 (auditoría money-path 2026-08-21) — el API no tenía path propio para
alertar al operador (las notificaciones Telegram vivían solo en el
orchestrator). Patrón espejo de routers/telegram_webhook.py:_send_telegram_reply
y de telegram_notifications.py del orchestrator: única fuente de verdad
`notification_settings` (channel='telegram', enabled) + bot_token vía Vault.

Track 6 (2026-08-22):
- parse_mode HTML (el Markdown legacy rompía con contenido dinámico sin
  escapar). Los CALLERS construyen el texto con html.escape en los valores
  dinámicos; aquí solo se fija el parse_mode.
- resolve_takeover_alerts: editMessageReplyMarkup sobre las alertas abiertas
  de una conversación (telegram_alert_messages) cuando el takeover se resuelve
  desde CUALQUIER canal (callback_query, /resolver, consola) — el botón
  "✅ Resolver" desaparece y nadie pisa el trabajo de otro operador.

Best-effort: nunca lanza; retorna True/False.
"""
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _resolve_telegram_config(supabase, tenant_id: str) -> tuple[str, Any]:
    """(bot_token, chat_id) del canal telegram del tenant. ("", "") si falta algo.
    El chat_id se devuelve CRUDO (sin coerción de tipo) — contrato histórico del
    sender (la Bot API acepta Integer|String, doc oficial sendMessage)."""
    try:
        res = (
            supabase.table("notification_settings")
            .select("config")
            .eq("tenant_id", tenant_id)
            .eq("channel", "telegram")
            .eq("enabled", True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.info(
            "[OP_ALERT] lookup notification_settings falló tenant=%s: %s",
            str(tenant_id)[:8], exc,
        )
        return "", ""
    rows = getattr(res, "data", None) or []
    if not rows:
        logger.info(
            "[OP_ALERT] tenant=%s sin canal telegram en notification_settings",
            str(tenant_id)[:8],
        )
        return "", ""
    config = dict(rows[0].get("config") or {})
    chat_id = config.get("chat_id") or config.get("telegram_chat_id")
    if not chat_id:
        logger.info(
            "[OP_ALERT] tenant=%s notification_settings sin chat_id",
            str(tenant_id)[:8],
        )
        return "", ""
    try:
        from vault_helper import VaultHelper, resolve_secret  # noqa: PLC0415
        token = resolve_secret(VaultHelper(supabase), config, "bot_token") or ""
    except Exception as exc:
        logger.warning(
            "[OP_ALERT] no pude resolver bot_token tenant=%s: %s",
            str(tenant_id)[:8], exc,
        )
        return "", ""
    return token.strip(), chat_id


def notify_operator_telegram(supabase, *, tenant_id: str, text: str) -> bool:
    """Envía `text` (HTML) al chat Telegram del operador del tenant.

    False si el tenant no tiene canal telegram configurado, falta el token
    o el envío HTTP falló — el caller decide si reintenta (el reconciliador
    del worker lo hace cada 15 min para pagado-sin-guía).
    """
    if not tenant_id or not text:
        return False
    token, chat_id = _resolve_telegram_config(supabase, tenant_id)
    if not token or not chat_id:
        return False
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.warning(
                "[OP_ALERT] telegram http=%s tenant=%s",
                resp.status_code, str(tenant_id)[:8],
            )
        return ok
    except Exception as exc:
        logger.warning(
            "[OP_ALERT] envío telegram falló tenant=%s: %s",
            str(tenant_id)[:8], exc,
        )
        return False


def resolve_takeover_alerts(
    supabase, *, tenant_id: str, conversation_id: str, resolved_via: str = "",
) -> int:
    """Quita el inline keyboard de las alertas de takeover ABIERTAS de la
    conversación y las marca resueltas. Devuelve cuántas se cerraron.

    Se llama al restaurar bot_active desde cualquier canal (callback_query del
    propio botón, comando /resolver, consola Inbox): el botón desaparece para
    TODO el grupo de operadores y un segundo operador no pisa al primero
    (anti doble-click cross-canal — doc oficial editMessageReplyMarkup: sin
    reply_markup se ELIMINA el teclado).

    Best-effort total: nunca lanza; 0 no significa error (puede no haber
    alertas abiertas — conversaciones anteriores a Track 6).
    """
    if not tenant_id or not conversation_id:
        return 0
    try:
        res = (
            supabase.table("telegram_alert_messages")
            .select("id, chat_id, message_id")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .is_("resolved_at", "null")
            .execute()
        )
        rows = getattr(res, "data", None) or []
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "[OP_ALERT] lookup telegram_alert_messages falló conv=%s: %s",
            str(conversation_id)[:8], exc,
        )
        return 0
    if not rows:
        return 0

    token, _own_chat = _resolve_telegram_config(supabase, tenant_id)
    closed = 0
    for row in rows:
        if token:
            try:
                with httpx.Client(timeout=10) as client:
                    client.post(
                        f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
                        json={
                            "chat_id": row["chat_id"],
                            "message_id": row["message_id"],
                            # Sin reply_markup: ELIMINA el teclado (anti doble-click).
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "[OP_ALERT] editMessageReplyMarkup falló msg=%s: %s",
                    row.get("message_id"), exc,
                )
        try:
            supabase.table("telegram_alert_messages").update({
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
            closed += 1
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "[OP_ALERT] mark resolved falló alert=%s: %s", row.get("id"), exc,
            )
    if closed:
        logger.info(
            "[OP_ALERT] %d alerta(s) takeover cerradas conv=%s via=%s",
            closed, str(conversation_id)[:8], resolved_via or "?",
        )
    return closed
