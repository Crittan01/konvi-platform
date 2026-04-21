"""
Despacho de notificaciones operacionales por evento.

Canales soportados:
- telegram (activo)
- email (preparado para fase SMTP; placeholder no bloqueante)
"""
import logging
from typing import Any

import httpx
from supabase import Client

logger = logging.getLogger("orchestrator.notifications")


def _build_takeover_text(payload: dict[str, Any]) -> str:
    tenant_id = str(payload.get("tenant_id", ""))
    conversation_id = str(payload.get("conversation_id", ""))
    customer_phone = str(payload.get("customer_phone", ""))
    previous_status = str(payload.get("previous_status") or "unknown")

    return (
        "🚨 Escalamiento humano requerido\n"
        f"Cliente: {customer_phone or 'N/A'}\n"
        f"Conversación: {conversation_id or 'N/A'}\n"
        f"Estado anterior: {previous_status}\n"
        "Acción: revisar Inbox en /dashboard/inbox\n"
        f"Tenant: {tenant_id or 'N/A'}"
    )


async def _send_telegram_notification(config: dict[str, Any], text: str) -> bool:
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()

    if not token or not chat_id:
        logger.warning("Telegram habilitado pero incompleto (falta bot_token/chat_id).")
        return True

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload)
    except Exception as exc:
        logger.error("Telegram unreachable: %s", exc)
        return False

    try:
        body = res.json()
    except Exception:
        body = {}

    if res.status_code >= 200 and res.status_code < 300 and body.get("ok") is True:
        return True

    error_code = int(body.get("error_code") or res.status_code)
    description = body.get("description") or res.text
    logger.error("Telegram error [%s]: %s", error_code, description)

    # Errores permanentes de configuración/token/chat => no reintentar.
    if error_code in {400, 401, 403, 404}:
        return True
    return False


def _dispatch_email_placeholder(config: dict[str, Any], payload: dict[str, Any]) -> bool:
    recipient = str(config.get("to_email") or config.get("recipient") or "").strip()
    if not recipient:
        logger.warning("Email habilitado sin recipient configurado. Se omite por ahora.")
        return True

    logger.info(
        "Email channel preparado (pendiente SMTP runtime). recipient=%s event=%s conv=%s",
        recipient,
        payload.get("event_type"),
        payload.get("conversation_id"),
    )
    return True


async def dispatch_human_takeover_event(supabase: Client, payload: dict[str, Any]) -> bool:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        logger.warning("Evento de takeover sin tenant_id. Se marca como manejado.")
        return True

    settings_res = (
        supabase.table("notification_settings")
        .select("channel, enabled, config")
        .eq("tenant_id", tenant_id)
        .eq("enabled", True)
        .in_("channel", ["telegram", "email"])
        .execute()
    )
    settings = settings_res.data or []

    if not settings:
        logger.info("Sin canales activos para takeover tenant=%s", tenant_id)
        return True

    text = _build_takeover_text(payload)
    transient_error = False

    for row in settings:
        channel = row.get("channel")
        config = row.get("config") or {}

        if channel == "telegram":
            ok = await _send_telegram_notification(config, text)
        elif channel == "email":
            ok = _dispatch_email_placeholder(config, payload)
        else:
            logger.info("Canal no soportado aún: %s", channel)
            ok = True

        if not ok:
            transient_error = True

    return not transient_error
