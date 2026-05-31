"""
Webhook bidireccional de Telegram para operadores.

Permite que el asesor restaure el bot desde Telegram sin abrir la Inbox UI.

Comandos soportados:
  /resolver {conversation_id}  → restaura bot_active en la conversación
  /estado {conversation_id}    → responde con el status actual

Autenticación:
  Telegram envía el header X-Telegram-Bot-Api-Secret-Token con el valor
  configurado en TELEGRAM_WEBHOOK_SECRET al registrar el webhook con setWebhook.
  Si la var no está configurada, el endpoint devuelve 503 (not configured).

INTERVENCION HUMANA REQUERIDA — configurar setWebhook:
  curl "https://api.telegram.org/bot{TOKEN}/setWebhook" \
    -d "url=https://konvi-api.onrender.com/api/v1/integrations/telegram/webhook" \
    -d "secret_token={TELEGRAM_WEBHOOK_SECRET}"

Referencia Telegram Bot API: https://core.telegram.org/bots/api#setwebhook
"""
import logging
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Telegram Webhook"])

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
CONVERSATION_STATUSES = {"bot_active", "human_takeover", "closed"}


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """
    Recibe updates de Telegram. Telegram espera respuesta 2xx inmediata.
    Autenticación: header X-Telegram-Bot-Api-Secret-Token.
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        logger.warning("[TG_WH] TELEGRAM_WEBHOOK_SECRET no configurado — endpoint deshabilitado")
        raise HTTPException(status_code=503, detail="Telegram webhook no configurado")

    if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        logger.warning("[TG_WH] Token inválido — request rechazado")
        raise HTTPException(status_code=401, detail="Token inválido")

    try:
        update = await request.json()
    except Exception:
        return JSONResponse(status_code=200, content={"ok": True})

    message = update.get("message") or update.get("edited_message") or {}
    text = str(message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")

    if not text or not chat_id:
        return JSONResponse(status_code=200, content={"ok": True})

    logger.info("[TG_WH] Comando recibido: chat=%s text=%r", chat_id, text[:80])
    reply = await _handle_command(text, chat_id)

    if reply:
        _send_telegram_reply(chat_id, reply, update)

    return JSONResponse(status_code=200, content={"ok": True})


async def _handle_command(text: str, chat_id: int) -> str:
    """Parsea el comando y ejecuta la acción. Retorna el texto de respuesta."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("resolver", "resolve"):
        return await _cmd_resolver(arg)
    if cmd in ("estado", "status"):
        return await _cmd_estado(arg)
    if cmd in ("ayuda", "help", "start"):
        return (
            "📋 *Comandos disponibles:*\n\n"
            "/resolver `{conv_id}` — restaura el bot en una conversación\n"
            "/estado `{conv_id}` — consulta el estado actual\n\n"
            "El `conv_id` es el UUID de la conversación (visible en la URL del Inbox)."
        )
    return ""


async def _cmd_resolver(conv_id: str) -> str:
    if not conv_id:
        return "⚠️ Uso: `/resolver {conversation_id}`"

    conv_id = conv_id.strip()
    supabase = _get_service_client()

    try:
        res = (
            supabase.table("conversations")
            .select("id, status, tenant_id")
            .eq("id", conv_id)
            .limit(1)
            .execute()
        )
        conv = (res.data or [None])[0]
        if not conv:
            return f"❌ Conversación `{conv_id[:8]}` no encontrada."

        current_status = conv.get("status", "")
        if current_status == "bot_active":
            return f"ℹ️ La conversación `{conv_id[:8]}` ya está en modo bot."

        supabase.table("conversations").update({"status": "bot_active"}).eq(
            "id", conv_id
        ).execute()

        logger.info("[TG_WH] bot_active restaurado: conv=%s", conv_id)
        return (
            f"*Bot activado* en conversación `{conv_id[:8]}`.\n"
            f"El bot retomará la atención en el próximo mensaje del cliente."
        )
    except Exception as e:
        logger.error("[TG_WH] Error en /resolver conv=%s: %s", conv_id, e)
        return "⚠️ Error al actualizar la conversación. Intenta de nuevo."


async def _cmd_estado(conv_id: str) -> str:
    if not conv_id:
        return "⚠️ Uso: `/estado {conversation_id}`"

    conv_id = conv_id.strip()
    supabase = _get_service_client()

    try:
        res = (
            supabase.table("conversations")
            .select("id, status, customer_phone, last_interaction_at")
            .eq("id", conv_id)
            .limit(1)
            .execute()
        )
        conv = (res.data or [None])[0]
        if not conv:
            return f"❌ Conversación `{conv_id[:8]}` no encontrada."

        status = conv.get("status", "N/D")
        phone = conv.get("customer_phone", "N/D")
        last_ts = str(conv.get("last_interaction_at") or "")[:16].replace("T", " ")

        status_icon = {"bot_active": "🤖", "human_takeover": "👤", "closed": "🔒"}.get(status, "❓")
        return (
            f"{status_icon} *Conversación* `{conv_id[:8]}`\n"
            f"Estado: *{status}*\n"
            f"Cliente: {phone}\n"
            f"Última interacción: {last_ts} UTC"
        )
    except Exception as e:
        logger.error("[TG_WH] Error en /estado conv=%s: %s", conv_id, e)
        return "⚠️ Error al consultar la conversación."


def _send_telegram_reply(chat_id: int, text: str, update: dict) -> None:
    """
    Envía respuesta al asesor en Telegram usando el bot_token del tenant
    propietario del chat_id.

    Rev. 105 Sem 2 F.12 (MA-10) — antes tomaba "primer tenant activo" lo que
    causaba cross-talk silencioso al haber 2+ tenants con Telegram. Ahora
    resuelve el tenant vía `tenant_provider_identity` (chat_id como
    provider_internal_id). Fallback al patrón legacy SOLO si la identidad
    no está registrada (warning explícito) — esto se removerá tras backfill
    completo de identidades.
    """
    supabase = _get_service_client()
    try:
        from lib.identity_registry import resolve_tenant_id

        tenant_id = resolve_tenant_id(supabase, "telegram", chat_id)

        if tenant_id:
            # Camino correcto: lookup config del tenant específico.
            settings_res = (
                supabase.table("notification_settings")
                .select("config")
                .eq("tenant_id", tenant_id)
                .eq("channel", "telegram")
                .eq("enabled", True)
                .limit(1)
                .execute()
            )
        else:
            # Fallback legacy temporal — pre-backfill identity registry.
            # Cuando todos los tenants estén registrados, este branch debe
            # removerse y el chat_id sin identidad rechazarse explícitamente.
            logger.warning(
                "[TG_WH] chat_id=%s sin identidad en tenant_provider_identity, "
                "usando fallback 'primer tenant activo' (legacy pre-backfill)",
                chat_id,
            )
            settings_res = (
                supabase.table("notification_settings")
                .select("config")
                .eq("channel", "telegram")
                .eq("enabled", True)
                .limit(1)
                .execute()
            )

        config = (settings_res.data or [{}])[0].get("config") or {}
        from vault_helper import VaultHelper, resolve_secret
        token = resolve_secret(VaultHelper(supabase), dict(config), "bot_token") or ""
        token = token.strip()
        if not token:
            logger.warning(
                "[TG_WH] Sin bot_token (tenant=%s, chat=%s)",
                tenant_id or "legacy", chat_id,
            )
            return

        with httpx.Client(timeout=10) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
    except Exception as e:
        logger.error("[TG_WH] Error enviando respuesta Telegram chat=%s: %s", chat_id, e)
