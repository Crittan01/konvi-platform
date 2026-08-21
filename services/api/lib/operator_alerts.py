"""Alertas operativas al operador del tenant vía Telegram, desde el API service.

B4 (auditoría money-path 2026-08-21) — el API no tenía path propio para
alertar al operador (las notificaciones Telegram vivían solo en el
orchestrator). Patrón espejo de routers/telegram_webhook.py:_send_telegram_reply
y de telegram_notifications.py del orchestrator: única fuente de verdad
`notification_settings` (channel='telegram', enabled) + bot_token vía Vault.

Best-effort: nunca lanza; retorna True/False.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def notify_operator_telegram(supabase, *, tenant_id: str, text: str) -> bool:
    """Envía `text` (Markdown) al chat Telegram del operador del tenant.

    False si el tenant no tiene canal telegram configurado, falta el token
    o el envío HTTP falló — el caller decide si reintenta (el reconciliador
    del worker lo hace cada 15 min para pagado-sin-guía).
    """
    if not tenant_id or not text:
        return False
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
        return False
    rows = getattr(res, "data", None) or []
    if not rows:
        logger.info(
            "[OP_ALERT] tenant=%s sin canal telegram en notification_settings",
            str(tenant_id)[:8],
        )
        return False
    config = dict(rows[0].get("config") or {})
    chat_id = config.get("chat_id") or config.get("telegram_chat_id")
    if not chat_id:
        logger.info(
            "[OP_ALERT] tenant=%s notification_settings sin chat_id",
            str(tenant_id)[:8],
        )
        return False
    try:
        from vault_helper import VaultHelper, resolve_secret  # noqa: PLC0415
        token = resolve_secret(VaultHelper(supabase), config, "bot_token") or ""
    except Exception as exc:
        logger.warning(
            "[OP_ALERT] no pude resolver bot_token tenant=%s: %s",
            str(tenant_id)[:8], exc,
        )
        return False
    if not token:
        return False
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
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
