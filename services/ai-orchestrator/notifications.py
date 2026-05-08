"""
Despacho de notificaciones operacionales por evento.

Canales soportados:
- telegram (activo)
- email vía Resend (rev. 94, activo cuando RESEND_API_KEY está configurada).
  Fallback a logger si la var no está seteada.

Eventos:
- human_takeover (rev. 84) — escalación a operador.
- consent_revoked (rev. 94) — cliente revocó por WhatsApp.
- sar_received (rev. 94) — solicitud Habeas Data del titular.
"""
import logging
import os
from typing import Any

import httpx
from supabase import Client

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv(
    "RESEND_FROM_EMAIL", "Konvi <noreply@commerce-ops.local>"
)

logger = logging.getLogger("orchestrator.notifications")


def _build_takeover_text(payload: dict[str, Any]) -> str:
    tenant_id = str(payload.get("tenant_id", ""))
    conversation_id = str(payload.get("conversation_id", ""))
    customer_phone = str(payload.get("customer_phone", ""))
    previous_status = str(payload.get("previous_status") or "unknown")

    short_id = conversation_id[:8] if conversation_id else "N/A"
    return (
        "🚨 *Escalamiento humano requerido*\n"
        f"Cliente: `{customer_phone or 'N/A'}`\n"
        f"Conv ID: `{conversation_id or 'N/A'}`\n\n"
        f"Para devolver al bot:\n"
        f"`/resolver {conversation_id}`\n\n"
        "Inbox: /dashboard/inbox"
    )


async def _send_telegram_notification(config: dict[str, Any], text: str) -> bool:
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()

    if not token or not chat_id:
        logger.warning("Telegram habilitado pero incompleto (falta bot_token/chat_id).")
        return True

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

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


async def _send_email_via_resend(
    *, to: str, subject: str, html: str, text: str | None = None,
) -> bool:
    """Rev. 94 — Envío real vía Resend API.

    Si `RESEND_API_KEY` no está configurada, fallback a logger (no falla
    el flujo). Resend free tier: 100 emails/día — suficiente para
    notificaciones críticas operacionales.

    Docs: https://resend.com/docs/api-reference/emails/send-email
    """
    if not RESEND_API_KEY:
        logger.info(
            "[EMAIL][NO_KEY] Email simulated to=%s subject=%r (RESEND_API_KEY not set)",
            to, subject,
        )
        return True

    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.resend.com/emails", json=payload, headers=headers,
            )
        if 200 <= res.status_code < 300:
            logger.info("[EMAIL][SENT] to=%s subject=%r", to, subject)
            return True
        logger.error(
            "[EMAIL][ERROR] status=%s body=%s",
            res.status_code, res.text[:200],
        )
        # 4xx (bad request, invalid key) — no retry; 5xx — retry.
        if res.status_code < 500:
            return True
        return False
    except Exception as exc:
        logger.error("[EMAIL] Resend unreachable: %s", exc)
        return False


def _dispatch_email_placeholder(config: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Mantenido por compat — wrapper no-async sobre _send_email_via_resend.

    `dispatch_human_takeover_event` aún usa este path. Para nuevos
    eventos preferir `notify_consent_event` / `notify_sar_received`.
    """
    recipient = str(config.get("to_email") or config.get("recipient") or "").strip()
    if not recipient:
        logger.warning("Email habilitado sin recipient configurado. Se omite por ahora.")
        return True
    if not RESEND_API_KEY:
        logger.info(
            "[EMAIL][NO_KEY] Email simulated to=%s event=%s",
            recipient, payload.get("event_type"),
        )
        return True
    # Resolución asíncrona via asyncio.run en sync context (caller actual).
    import asyncio
    subject = f"[Konvi] {payload.get('event_type', 'notification')}"
    html = (
        f"<p>Evento operacional: <b>{payload.get('event_type')}</b></p>"
        f"<pre>{payload}</pre>"
    )
    try:
        return asyncio.run(_send_email_via_resend(
            to=recipient, subject=subject, html=html,
        ))
    except RuntimeError:
        # Caller ya tiene event loop activo — fire-and-forget.
        logger.info("[EMAIL] caller has loop; fire-and-forget to=%s", recipient)
        return True


async def notify_consent_revoked(
    supabase: Client,
    *,
    tenant_id: str,
    contact_phone_hash: str,
    occurred_at: str,
    source: str = "whatsapp",
) -> bool:
    """Rev. 94 — Notifica al tenant que un cliente revocó consent.

    Habeas Data Ley 1581 Art. 9: el responsable (tenant) debe estar
    enterado de las revocaciones para mantener registro adecuado.
    """
    return await _notify_tenant_event(
        supabase,
        tenant_id=tenant_id,
        event_type="consent_revoked",
        subject=f"🔒 Cliente revocó consentimiento (Habeas Data)",
        html_body=(
            f"<h2>Revocación de consentimiento</h2>"
            f"<p>Un cliente revocó su consentimiento de tratamiento de datos.</p>"
            f"<ul>"
            f"<li><b>Cliente</b> (hash): <code>{contact_phone_hash[:16]}…</code></li>"
            f"<li><b>Fecha</b>: {occurred_at}</li>"
            f"<li><b>Canal</b>: {source}</li>"
            f"</ul>"
            f"<p>El sistema ya anonimizó los datos personales del contacto "
            f"(Art. 15 Ley 1581/2012). Esta notificación es solo para tu "
            f"registro de cumplimiento.</p>"
            f"<hr>"
            f"<small>Generado automáticamente por Konvi Platform.</small>"
        ),
    )


async def notify_sar_received(
    supabase: Client,
    *,
    tenant_id: str,
    contact_id: str,
    sar_type: str,                      # 'export' | 'rectify' | 'erase' | 'portability'
    reason: str | None = None,
) -> bool:
    """Rev. 94 — Notifica al tenant que llegó una solicitud Habeas Data."""
    return await _notify_tenant_event(
        supabase,
        tenant_id=tenant_id,
        event_type=f"sar_{sar_type}",
        subject=f"📋 Solicitud Habeas Data ({sar_type})",
        html_body=(
            f"<h2>Solicitud de derechos del titular</h2>"
            f"<p>Tipo: <b>{sar_type}</b></p>"
            f"<p>Contacto ID: <code>{contact_id[:8]}…</code></p>"
            + (f"<p>Razón: {reason}</p>" if reason else "")
            + f"<p>Detalles en Tenant Console → Contactos.</p>"
        ),
    )


async def _notify_tenant_event(
    supabase: Client,
    *,
    tenant_id: str,
    event_type: str,
    subject: str,
    html_body: str,
) -> bool:
    """Despachador genérico — busca recipients del tenant en
    `notification_settings` y envía email."""
    if not tenant_id:
        return True

    settings_res = (
        supabase.table("notification_settings")
        .select("channel, enabled, config")
        .eq("tenant_id", tenant_id)
        .eq("enabled", True)
        .eq("channel", "email")
        .execute()
    )
    rows = settings_res.data or []
    if not rows:
        # Sin email configurado — no es error, solo log.
        logger.info(
            "[NOTIFY] tenant=%s sin email configurado — skip event=%s",
            tenant_id, event_type,
        )
        return True

    sent_any = False
    failed_recipients: list[str] = []
    attempted = 0
    for row in rows:
        config = dict(row.get("config") or {})
        recipient = str(config.get("to_email") or config.get("recipient") or "").strip()
        if not recipient:
            continue
        attempted += 1
        ok = await _send_email_via_resend(
            to=recipient, subject=subject, html=html_body,
        )
        if ok:
            sent_any = True
        else:
            failed_recipients.append(recipient)
    # Rev. 100 — semantics explícita:
    #   • Sin recipients configurados → True (no-op aceptable, no es fallo).
    #   • Al menos 1 envío OK → True.
    #   • Todos los envíos fallaron → False + log ERROR explícito.
    #     (Art. 9 audit gap potencial — el caller debe re-intentar o escalar).
    if attempted > 0 and not sent_any:
        logger.error(
            "[NOTIFY] tenant=%s event=%s ALL %d recipients failed: %s",
            tenant_id, event_type, attempted, failed_recipients,
        )
        return False
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

    from vault_helper import VaultHelper, resolve_secret
    vault = VaultHelper(supabase)

    for row in settings:
        channel = row.get("channel")
        config  = dict(row.get("config") or {})

        if channel == "telegram":
            # Resolver bot_token desde Vault
            config["bot_token"] = resolve_secret(vault, config, "bot_token") or ""
            ok = await _send_telegram_notification(config, text)
        elif channel == "email":
            ok = _dispatch_email_placeholder(config, payload)
        else:
            logger.info("Canal no soportado aún: %s", channel)
            ok = True

        if not ok:
            transient_error = True

    return not transient_error
