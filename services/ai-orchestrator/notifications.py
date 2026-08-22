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
import html
import os
import re
from typing import Any

import httpx
from supabase import Client

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv(
    "RESEND_FROM_EMAIL", "Konvi <noreply@commerce-ops.local>"
)
# URL pública de la Console — usada para deep-links accionables en Telegram/email.
# Mismo env que Server Actions / emails (render.yaml key APP_URL). Default = dominio
# real productivo (no un placeholder) para que el link nunca quede roto si el env
# no está seteado en el servicio orchestrator.
APP_URL = os.getenv("APP_URL", "https://konvi-web.onrender.com").rstrip("/")

logger = logging.getLogger("orchestrator.notifications")


def _mask_email_addr(email: str) -> str:
    """Enmascara PII para logs: 'ju***@dominio.com' (patrón de client_notifications)."""
    local, sep, domain = (email or "").partition("@")
    if not sep:
        return "***"
    return f"{local[:2]}***@{domain}"


def _is_suppressed(supabase: Any, email: str) -> bool:
    """True si la dirección está en la suppression list local (Track 6 Resend).

    La verdad vive en services/api/lib/email_suppression.py (compartida con el
    API) — import perezoso con el patrón canónico orchestrator→api (worker.py).
    Fail-open: cualquier error = NO suprimido (Resend aplica su propia lista).
    """
    try:
        import sys
        from pathlib import Path
        _api_root = Path(__file__).resolve().parents[1] / "api"
        if str(_api_root) not in sys.path:
            sys.path.insert(0, str(_api_root))
        from lib.email_suppression import is_email_suppressed  # noqa: PLC0415
        return is_email_suppressed(supabase, email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[EMAIL][SUPPRESSION] check falló (fail-open): %s", exc)
        return False


def _register_telegram_identity(supabase: Client, tenant_id: str, chat_id: Any) -> None:
    """Auto-vincula (tenant_id, telegram, chat_id) en tenant_provider_identity.

    CRÍTICO (fix gap "comandos muertos"): los comandos /resolver /estado del
    webhook resuelven el tenant del operador vía `resolve_tenant_id(...telegram...)`
    y rechazan chats no mapeados. Antes NADA poblaba ese mapeo → todo comando
    caía en silencio. La ruta de SALIDA (esta notificación) es justo donde
    conocemos AMBOS lados del par (tenant_id + chat_id destino), así que
    registramos la identidad al enviar: cuando el operador ve el mensaje con
    `/resolver`, su chat ya está vinculado y el comando responde.

    Best-effort: NUNCA rompe el envío de la notificación. Una colisión
    cross-tenant (mismo chat_id apuntando a 2 tenants) se loguea como señal de
    seguridad pero no aborta la alerta.
    """
    if not tenant_id or chat_id in (None, ""):
        return
    try:
        import sys
        from pathlib import Path
        # Patrón canónico ai-orchestrator → services/api/lib (worker.py:2131).
        _api_root = Path(__file__).resolve().parents[1] / "api"
        if str(_api_root) not in sys.path:
            sys.path.insert(0, str(_api_root))
        from lib.identity_registry import (  # noqa: PLC0415
            register_identity,
        )
        register_identity(
            supabase,
            tenant_id,
            "telegram",
            chat_id,
            metadata={"source": "notification_autolink"},
            mark_verified=True,
        )
    except Exception as exc:  # incl. IdentityRegistryError (colisión cross-tenant)
        # No rompemos la notificación: solo dejamos rastro. Si es colisión
        # cross-tenant es un misconfig real (2 tenants con el mismo chat_id).
        logger.warning(
            "[NOTIFY] auto-link telegram identity falló tenant=%s chat=%s: %s",
            (tenant_id[:8] if tenant_id else "?"), chat_id, exc,
        )


def _build_takeover_text(payload: dict[str, Any]) -> str:
    """Texto de la alerta de takeover en HTML (Track 6: parse_mode HTML con
    html.escape en TODO valor dinámico — adiós al "can't parse entities" del
    Markdown legacy cuando el teléfono/id traía caracteres especiales)."""
    conversation_id = str(payload.get("conversation_id", ""))
    customer_phone = str(payload.get("customer_phone", ""))

    inbox_link = f"{APP_URL}/dashboard/inbox"
    return (
        "🚨 <b>Escalamiento humano requerido</b>\n"
        f"Cliente: <code>{html.escape(customer_phone or 'N/A')}</code>\n"
        f"Conv ID: <code>{html.escape(conversation_id or 'N/A')}</code>\n\n"
        f"Para devolver al bot:\n"
        f"<code>/resolver {html.escape(conversation_id)}</code>\n\n"
        # URL absoluta: un path relativo `/dashboard/inbox` Telegram lo trata
        # como comando `/dashboard` y no es clickeable.
        f"Inbox: {html.escape(inbox_link)}"
    )


def _takeover_reply_markup(conversation_id: str) -> dict[str, Any] | None:
    """Inline keyboard de la alerta de takeover (Track 6).

    Botón "✅ Resolver": callback_data `resolve:{conv_id}` (44 bytes — el límite
    oficial es 1-64 bytes, doc InlineKeyboardButton). El webhook
    (telegram_webhook.py) atiende el callback_query con la MISMA acción del
    comando /resolver + answerCallbackQuery + editMessageReplyMarkup.
    """
    conv = str(conversation_id or "").strip()
    if not conv:
        return None
    return {
        "inline_keyboard": [[
            {"text": "✅ Resolver (devolver al bot)", "callback_data": f"resolve:{conv}"},
        ]],
    }


async def _send_telegram_notification(
    config: dict[str, Any],
    text: str,
    reply_markup: dict[str, Any] | None = None,
    alert_context: dict[str, Any] | None = None,
) -> bool:
    token = str(config.get("bot_token") or "").strip()
    chat_id = str(config.get("chat_id") or "").strip()

    if not token or not chat_id:
        logger.warning("Telegram habilitado pero incompleto (falta bot_token/chat_id).")
        return True

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        # Track 6 (2026-08-22): parse_mode HTML — el Markdown legacy rompía con
        # contenido dinámico sin escapar ("can't parse entities") y la alerta
        # se perdía. Con html.escape en los builders el fallback ya no hace
        # falta: se elimina el reintento en texto plano.
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

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
        # Track 6: persistir message_id de la alerta (editMessageReplyMarkup al
        # resolver desde cualquier canal). Best-effort — nunca rompe la alerta.
        message_id = ((body.get("result") or {}).get("message_id"))
        if alert_context and message_id is not None:
            _persist_alert_message(alert_context, chat_id, message_id)
        return True

    error_code = int(body.get("error_code") or res.status_code)
    description = body.get("description") or res.text
    logger.error("Telegram error [%s]: %s", error_code, description)

    # Errores permanentes de configuración/token/chat => no reintentar.
    if error_code in {400, 401, 403, 404}:
        return True
    return False


def _persist_alert_message(
    alert_context: dict[str, Any], chat_id: str, message_id: int,
) -> None:
    """Inserta (tenant, conversación, chat, message_id) en telegram_alert_messages.

    UNIQUE(chat_id, message_id) → la re-entrega del evento pgmq no duplica la
    fila. Nunca lanza: la alerta ya fue entregada, la persistencia es para el
    editMessageReplyMarkup posterior (anti doble-click cross-canal).
    """
    try:
        supabase = alert_context.get("supabase")
        if supabase is None:
            return
        supabase.table("telegram_alert_messages").insert({
            "tenant_id": alert_context.get("tenant_id"),
            "conversation_id": alert_context.get("conversation_id"),
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "alert_type": "takeover",
        }).execute()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "duplicate key" not in msg and "23505" not in msg:
            logger.warning("[NOTIFY] persist alert message_id falló: %s", exc)


async def _send_email_via_resend(
    *, to: str, subject: str, html: str, text: str | None = None,
    idempotency_key: str | None = None, reply_to: str | None = None,
    tags: list[dict] | None = None, supabase: Any = None,
) -> bool:
    """Rev. 94 — Envío real vía Resend API.

    Si `RESEND_API_KEY` no está configurada, fallback a logger (no falla
    el flujo). Resend free tier: 100 emails/día y 3.000/mes — suficiente para
    notificaciones críticas operacionales.

    `idempotency_key` (BLOQUE H): opcional, para callers con reintento
    (ej. cron backup VOIDED) — Resend dedupe 24h, máx 256 chars.

    `tags` (Track 6, 2026-08-22): pares name/value (≤256 chars) que viajan al
    webhook de eventos — routing por tenant + correlación envío↔evento
    (la doc multi-tenant oficial prescribe tags para esto).

    `supabase` (Track 6, 2026-08-22): si se provee, se consulta la suppression
    list local (email_events vía webhook Resend) antes de gastar cuota — un
    destinatario suprimido NO se envía y retorna False (no entregado; el caller
    decide si reintenta — la supresión típica es permanente hasta removal manual).

    Docs: https://resend.com/docs/api-reference/emails/send-email
    """
    if not RESEND_API_KEY:
        logger.info(
            "[EMAIL][NO_KEY] Email simulated to=%s subject=%r (RESEND_API_KEY not set)",
            to, subject,
        )
        return True

    if supabase is not None and _is_suppressed(supabase, to):
        logger.info(
            "[EMAIL][SUPPRESSED] envío omitido (suppression list) to=%s subject=%r",
            _mask_email_addr(to), subject,
        )
        return False

    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        # Track 6 (2026-08-22): text/plain SIEMPRE (multipart recomendado por
        # Resend — mejor scoring anti-spam). Fallback: strip básico del HTML.
        "text": text or re.sub(r"<[^>]+>", " ", html).strip()[:4000],
    }
    if reply_to:
        # Los correos salen de `noreply@` de la PLATAFORMA, pero quien vende es el tenant.
        # Sin esto, el comprador que le da "Responder" a su comprobante escribe a un buzón
        # que nadie lee — y responder es lo que una persona hace de verdad, aunque el
        # documento traiga impreso el correo del vendedor.
        # Campo verificado en la doc oficial de Resend: `reply_to`, string o array.
        payload["reply_to"] = reply_to
    if tags:
        payload["tags"] = tags

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        # Track 6 (2026-08-22): User-Agent explícito — Resend lo exige (403 error
        # 1010 sin él); el default de httpx funcionaba por accidente, no por diseño.
        "User-Agent": "konvi-orchestrator/1.0",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:256]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.resend.com/emails", json=payload, headers=headers,
            )
        # Track 6: headers de cuota (free tier 100/día + 3.000/mes).
        _qd = res.headers.get("x-resend-daily-quota")
        _qm = res.headers.get("x-resend-monthly-quota")
        if _qd or _qm:
            logger.info("[EMAIL] resend quota daily=%s monthly=%s", _qd, _qm)
        if 200 <= res.status_code < 300:
            logger.info("[EMAIL][SENT] to=%s subject=%r", to, subject)
            return True
        logger.error(
            "[EMAIL][ERROR] status=%s body=%s",
            res.status_code, res.text[:200],
        )
        # BLOQUE H (review Fable HIGH): el bool es "¿el email fue ACEPTADO
        # (2xx)?" — verdad de entrega, no "¿reintentar?". Antes devolvía True
        # en cualquier 4xx (incl. 429 rate-limit del free tier 100/día); en el
        # path donde el email GOBIERNA (refund sin conversación) eso marcaba
        # "cliente notificado" sin haberlo notificado → sync VOIDED + audit
        # 'completed' falso. Ahora solo 2xx = entregado; el caller decide si
        # reintentar (el cron de refund reintenta el próximo ciclo).
        return False
    except Exception as exc:
        logger.error("[EMAIL] Resend unreachable: %s", exc)
        return False


async def _dispatch_email_event(
    config: dict[str, Any], payload: dict[str, Any], supabase: Any = None,
) -> bool:
    """Envía el email de un evento operacional (takeover) vía Resend.

    `dispatch_human_takeover_event` usa este path. Para nuevos eventos
    preferir `notify_consent_event` / `notify_sar_received`.

    FIX gap "email nunca envía en producción": la versión previa
    (`_dispatch_email_placeholder`) llamaba `asyncio.run(...)` dentro del
    event loop async del worker → RuntimeError → return True SIN enviar. El
    único caller (`dispatch_human_takeover_event`) YA es async, así que aquí
    simplemente `await` el envío real. Sin loops anidados.
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
    event_type = payload.get("event_type", "notification")
    subject = f"[Konvi] {event_type}"
    conv_id = str(payload.get("conversation_id") or "")
    inbox_link = f"{APP_URL}/dashboard/inbox"
    html = (
        f"<p>Evento operacional: <b>{event_type}</b></p>"
        + (f"<p>Conversación: <code>{conv_id}</code></p>" if conv_id else "")
        + f'<p><a href="{inbox_link}">Abrir Inbox</a></p>'
    )
    return await _send_email_via_resend(
        to=recipient, subject=subject, html=html,
        tags=[
            {"name": "tenant_id", "value": str(payload.get("tenant_id") or "")},
            {"name": "event_type", "value": str(event_type)},
        ],
        supabase=supabase,
    )


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
            # Track 6 (2026-08-22): tags viajan al webhook de eventos (routing
            # tenant + correlación envío↔evento de entrega/bounce/queja).
            tags=[
                {"name": "tenant_id", "value": str(tenant_id)},
                {"name": "event_type", "value": str(event_type)},
            ],
            # Track 6: suppression list local — no gastar cuota en suprimidos.
            supabase=supabase,
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
            # Auto-vincula el chat destino → tenant ANTES/independiente del envío,
            # para que `/resolver` desde ese chat resuelva su tenant (comandos vivos).
            _register_telegram_identity(supabase, tenant_id, config.get("chat_id"))
            # Track 6: inline keyboard "✅ Resolver" + persistencia del message_id
            # (editMessageReplyMarkup al resolver desde cualquier canal).
            conv_id = str(payload.get("conversation_id") or "")
            ok = await _send_telegram_notification(
                config, text,
                reply_markup=_takeover_reply_markup(conv_id),
                alert_context={
                    "supabase": supabase,
                    "tenant_id": tenant_id,
                    "conversation_id": conv_id,
                },
            )
        elif channel == "email":
            ok = await _dispatch_email_event(config, payload, supabase)
        else:
            logger.info("Canal no soportado aún: %s", channel)
            ok = True

        if not ok:
            transient_error = True

    return not transient_error
