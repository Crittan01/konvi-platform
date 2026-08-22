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

Vinculación chat_id → tenant (RBAC de comandos):
  Un comando solo se ejecuta si el chat_id está mapeado a un tenant en
  `tenant_provider_identity` (provider='telegram'). Ese mapeo se puebla de dos
  formas, ambas automáticas (sin backfill SQL manual):
    1) al ENVIAR cualquier notificación/escalación al chat del operador
       (notifications._register_telegram_identity), y
    2) como self-heal en este webhook: si llega un comando de un chat aún no
       mapeado, se resuelve el tenant contra `notification_settings`
       (channel='telegram', config.chat_id) y, si hay UNA coincidencia
       inequívoca, se registra la identidad y se ejecuta el comando.
  Un chat sin notificación previa ni fila en notification_settings NO puede
  ejecutar comandos (origen no autorizado).

INTERVENCION HUMANA REQUERIDA — registrar el webhook (una vez por bot del tenant):
  Desde Track 6 (2026-08-22) el alta es AUTOMÁTICA vía
  `POST /api/v1/integrations/telegram/setup` (routers/integrations.py —
  getMe → setWebhook con allowed_updates=["message","callback_query"] →
  setMyCommands → getWebhookInfo; cierra M17). El camino manual con curl sigue
  siendo válido como contingencia:
    curl "https://api.telegram.org/bot{TOKEN}/setWebhook" \
      -d "url=https://konvi-api.onrender.com/api/v1/integrations/telegram/webhook" \
      -d "secret_token={TELEGRAM_WEBHOOK_SECRET}"
  CRITERIO DE EXITO: getWebhookInfo devuelve la URL anterior y last_error_date vacío.
  NOTA: la URL correcta incluye el segmento /integrations (prefijo del router en
  main.py:295). La UI ya muestra la URL completa — fuente única de verdad:
  apps/web/lib/webhook-urls.ts (WEBHOOK_PATHS.telegram), cubierta por
  webhook-urls.test.ts.

Referencia Telegram Bot API: https://core.telegram.org/bots/api#setwebhook
"""
import hmac
import html
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

    Updates soportados (allowed_updates del setup):
      - message / edited_message → comandos /resolver /estado /ayuda
      - callback_query (Track 6) → botón inline "✅ Resolver" de la alerta de
        takeover: misma acción del comando + answerCallbackQuery (obligatorio
        — sin él el botón queda "cargando" para siempre en el cliente) +
        editMessageReplyMarkup (el teclado desaparece: anti doble-click).
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        logger.warning("[TG_WH] TELEGRAM_WEBHOOK_SECRET no configurado — endpoint deshabilitado")
        raise HTTPException(status_code=503, detail="Telegram webhook no configurado")

    # A7.5 finiquito: constant-time comparison evita timing attack sobre el secret.
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, TELEGRAM_WEBHOOK_SECRET):
        logger.warning("[TG_WH] Token inválido — request rechazado")
        raise HTTPException(status_code=401, detail="Token inválido")

    try:
        update = await request.json()
    except Exception:
        return JSONResponse(status_code=200, content={"ok": True})

    # Track 6: callback_query del inline keyboard (hoy se descartaba en silencio).
    callback_query = update.get("callback_query") or {}
    if callback_query:
        await _handle_callback_query(callback_query)
        return JSONResponse(status_code=200, content={"ok": True})

    message = update.get("message") or update.get("edited_message") or {}
    text = str(message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    # RBAC intra-chat / auditoría: registramos QUIÉN emitió el comando dentro
    # del grupo (el grupo sigue siendo la frontera de confianza — cualquier
    # miembro puede ejecutar — pero dejamos rastro del autor). Telegram entrega
    # el autor en message.from.
    from_user = message.get("from") or {}
    author_id = from_user.get("id")
    author_username = from_user.get("username") or from_user.get("first_name") or "?"

    if not text or not chat_id:
        return JSONResponse(status_code=200, content={"ok": True})

    logger.info(
        "[TG_WH] Comando recibido: chat=%s author=%s(@%s) text=%r",
        chat_id, author_id, author_username, text[:80],
    )

    # A6.2.7 finiquito 2026-06-24 (super-audit + triage wl982c7yb CRITICAL):
    # SEGURIDAD MULTI-TENANT. Antes los comandos /resolver /estado leían/mutaban
    # conversaciones por conv_id del INPUT del operador SIN filtrar por tenant →
    # un operador del tenant B podía escribir "/resolver {conv_id_de_A}" y mutar
    # o leer PII (customer_phone) de la conversación de OTRO tenant. La verdadera
    # solución NO es .eq("tenant_id") ciego (no hay tenant en scope del comando):
    # el chat_id ES la identidad del operador → resolvemos su tenant vía
    # tenant_provider_identity ANTES de ejecutar, y rechazamos chats no mapeados.
    supabase = _get_service_client()
    from lib.identity_registry import resolve_tenant_id
    tenant_id = resolve_tenant_id(supabase, "telegram", chat_id)
    if not tenant_id:
        # Self-heal (fix gap "comandos muertos"): el chat aún no está en
        # tenant_provider_identity, pero PUEDE ser un operador legítimo cuyo
        # chat_id vive en notification_settings (lo configuró por la UI) y
        # todavía no recibió ninguna notificación que lo auto-vinculara. Lo
        # resolvemos ahí y, si hay UNA coincidencia inequívoca, lo registramos.
        # Si es ambiguo (mismo chat_id en 2 tenants) o inexistente → rechazo.
        tenant_id = _resolve_and_link_via_notification_settings(supabase, chat_id)
    if not tenant_id:
        # Chat no vinculado a ningún tenant → NO ejecutamos comando ni respondemos
        # (sin tenant no hay bot_token con qué responder, y es un origen no
        # autorizado).
        logger.warning(
            "[TG_WH] chat_id=%s SIN tenant (ni identity ni notification_settings) — "
            "comando RECHAZADO (origen no autorizado)",
            chat_id,
        )
        return JSONResponse(status_code=200, content={"ok": True})

    reply = await _handle_command(text, chat_id, tenant_id)

    if reply:
        _send_telegram_reply(chat_id, reply, tenant_id)

    return JSONResponse(status_code=200, content={"ok": True})


# ─── Track 6 — callback_query (inline keyboard de la alerta de takeover) ──────

def _resolve_bot_token(supabase, tenant_id: str) -> str:
    """bot_token del tenant desde notification_settings + Vault (misma fuente
    única que el resto del módulo). "" si falta — el caller decide."""
    try:
        settings_res = (
            supabase.table("notification_settings")
            .select("config")
            .eq("tenant_id", tenant_id)
            .eq("channel", "telegram")
            .eq("enabled", True)
            .limit(1)
            .execute()
        )
        config = (settings_res.data or [{}])[0].get("config") or {}
        from vault_helper import VaultHelper, resolve_secret
        token = resolve_secret(VaultHelper(supabase), dict(config), "bot_token") or ""
        return token.strip()
    except Exception as exc:
        logger.warning("[TG_WH] resolve bot_token falló tenant=%s: %s", tenant_id[:8], exc)
        return ""


def _telegram_api_post(token: str, method: str, payload: dict) -> None:
    """POST fire-and-log a la Bot API (best-effort: nunca lanza)."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
        if not (200 <= resp.status_code < 300):
            logger.warning("[TG_WH] %s http=%s body=%s", method, resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("[TG_WH] %s unreachable: %s", method, exc)


async def _handle_callback_query(cq: dict) -> None:
    """Atiende el callback_query del inline keyboard (Track 6).

    Flujo (doc oficial CallbackQuery/answerCallbackQuery/editMessageReplyMarkup):
      1. Mismo RBAC que los comandos: chat_id → tenant (identity + self-heal).
      2. `resolve:{conv_id}` → la MISMA acción de /resolver (que a su vez
         cierra las alertas abiertas vía resolve_takeover_alerts — incluido el
         markup de ESTE mensaje: anti doble-click).
      3. answerCallbackQuery SIEMPRE (obligatorio: si no, el botón queda
         "cargando" en el cliente; el texto tiene tope de 200 chars).
    """
    cq_id = str(cq.get("id") or "")
    data = str(cq.get("data") or "")
    message = cq.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    from_user = cq.get("from") or {}
    author = from_user.get("username") or from_user.get("first_name") or "?"

    if not cq_id:
        return
    logger.info(
        "[TG_WH] callback_query chat=%s author=@%s data=%r",
        chat_id, author, data[:60],
    )

    supabase = _get_service_client()
    from lib.identity_registry import resolve_tenant_id
    tenant_id = resolve_tenant_id(supabase, "telegram", chat_id)
    if not tenant_id:
        tenant_id = _resolve_and_link_via_notification_settings(supabase, chat_id)

    token = _resolve_bot_token(supabase, tenant_id) if tenant_id else ""
    if not tenant_id or not token:
        # Sin tenant no hay bot_token con qué responder/editar. Telegram
        # reintentará un rato y luego mostrará el spinner expirado — mismo
        # comportamiento seguro que un comando no autorizado.
        logger.warning(
            "[TG_WH] callback_query de chat=%s SIN tenant/token — ignorado",
            chat_id,
        )
        return

    if data.startswith("resolve:"):
        conv_id = data[len("resolve:"):].strip()
        # _cmd_resolver restaura bot_active + cierra las alertas abiertas
        # (editMessageReplyMarkup en cada una, incluida esta).
        reply = await _cmd_resolver(conv_id, tenant_id)
        # answerCallbackQuery: texto ≤200 chars (límite oficial).
        _telegram_api_post(token, "answerCallbackQuery", {
            "callback_query_id": cq_id,
            "text": reply[:200],
        })
    else:
        _telegram_api_post(token, "answerCallbackQuery", {
            "callback_query_id": cq_id,
            "text": "Acción no reconocida.",
        })


def _resolve_and_link_via_notification_settings(supabase, chat_id) -> str:
    """Fallback de resolución tenant para un chat aún no registrado.

    Busca en `notification_settings` (channel='telegram', enabled=true) la fila
    cuyo `config.chat_id` coincide con este chat. Si hay EXACTAMENTE una
    coincidencia → registra la identidad (self-heal, O(1) las próximas veces) y
    devuelve el tenant. Si hay 0 o >1 → devuelve "" (rechazo seguro: un chat_id
    ambiguo entre 2 tenants NO debe poder ejecutar comandos sobre ninguno).

    Cross-tenant por diseño (resolución de identidad externa, igual que
    identity_registry.resolve_tenant_id) → exento del lint de tenant_filter.
    """
    if chat_id in (None, ""):
        return ""
    target = str(chat_id).strip()
    try:
        res = (
            supabase.table("notification_settings")  # tenant_filter:exempt:resolution_lookup_by_provider_internal_id
            .select("tenant_id, config")
            .eq("channel", "telegram")
            .eq("enabled", True)
            .execute()
        )
    except Exception as exc:
        logger.error("[TG_WH] fallback lookup notification_settings falló: %s", exc)
        return ""

    matches: list[str] = []
    for row in (getattr(res, "data", None) or []):
        cfg = dict(row.get("config") or {})
        cfg_chat = cfg.get("chat_id") or cfg.get("telegram_chat_id")
        if cfg_chat is not None and str(cfg_chat).strip() == target:
            tid = str(row.get("tenant_id") or "").strip()
            if tid and tid not in matches:
                matches.append(tid)

    if len(matches) != 1:
        if len(matches) > 1:
            logger.warning(
                "[TG_WH] chat_id=%s AMBIGUO — %d tenants lo declaran en "
                "notification_settings; comando rechazado.",
                chat_id, len(matches),
            )
        return ""

    tenant_id = matches[0]
    try:
        from lib.identity_registry import register_identity
        register_identity(
            supabase,
            tenant_id,
            "telegram",
            chat_id,
            metadata={"source": "webhook_self_heal"},
            mark_verified=True,
        )
        logger.info(
            "[TG_WH] chat_id=%s auto-vinculado a tenant=%s (self-heal).",
            chat_id, tenant_id[:8],
        )
    except Exception as exc:
        # No pudimos persistir el mapeo, pero la resolución fue inequívoca →
        # ejecutamos igual este comando (best-effort; re-registrará al próximo).
        logger.warning(
            "[TG_WH] chat_id=%s resuelto a tenant=%s pero register_identity "
            "falló: %s (comando procede igual).",
            chat_id, tenant_id[:8], exc,
        )
    return tenant_id


async def _handle_command(text: str, chat_id: int, tenant_id: str) -> str:
    """Parsea el comando y ejecuta la acción. Retorna el texto de respuesta.

    `tenant_id` ya resuelto del chat_id (A6.2.7) — todas las queries de los
    comandos DEBEN filtrar por él para aislamiento cross-tenant.
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("resolver", "resolve"):
        return await _cmd_resolver(arg, tenant_id)
    if cmd in ("estado", "status"):
        return await _cmd_estado(arg, tenant_id)
    if cmd in ("ayuda", "help", "start"):
        return (
            "📋 <b>Comandos disponibles:</b>\n\n"
            "/resolver <code>{conv_id}</code> — restaura el bot en una conversación\n"
            "/estado <code>{conv_id}</code> — consulta el estado actual\n\n"
            "El <code>conv_id</code> es el UUID de la conversación (visible en la URL del Inbox)."
        )
    return ""


async def _cmd_resolver(conv_id: str, tenant_id: str) -> str:
    if not conv_id:
        return "⚠️ Uso: <code>/resolver {conversation_id}</code>"

    conv_id = conv_id.strip()
    supabase = _get_service_client()

    try:
        # A6.2.7: filtrar por tenant del operador (resuelto del chat_id) → un
        # operador no puede tocar conversaciones de otro tenant aunque pase su
        # conv_id. Si el conv_id es de otro tenant, la query retorna 0 filas.
        res = (
            supabase.table("conversations")
            .select("id, status, tenant_id")
            .eq("id", conv_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        conv = (res.data or [None])[0]
        if not conv:
            return f"❌ Conversación <code>{html.escape(conv_id[:8])}</code> no encontrada."

        current_status = conv.get("status", "")
        if current_status == "bot_active":
            return f"ℹ️ La conversación <code>{html.escape(conv_id[:8])}</code> ya está en modo bot."

        supabase.table("conversations").update({"status": "bot_active"}).eq(
            "id", conv_id
        ).eq("tenant_id", tenant_id).execute()

        # Track 6: cerrar las alertas de takeover abiertas (quita el inline
        # keyboard vía editMessageReplyMarkup — anti doble-click cross-canal).
        try:
            from lib.operator_alerts import resolve_takeover_alerts  # noqa: PLC0415
            resolve_takeover_alerts(
                supabase, tenant_id=tenant_id, conversation_id=conv_id,
                resolved_via="telegram_command",
            )
        except Exception as _alert_exc:  # noqa: BLE001 — nunca rompe el resolve
            logger.info("[TG_WH] resolve_takeover_alerts skip conv=%s: %s", conv_id[:8], _alert_exc)

        logger.info("[TG_WH] bot_active restaurado: conv=%s", conv_id)
        return (
            f"<b>Bot activado</b> en conversación <code>{html.escape(conv_id[:8])}</code>.\n"
            f"El bot retomará la atención en el próximo mensaje del cliente."
        )
    except Exception as e:
        logger.error("[TG_WH] Error en /resolver conv=%s: %s", conv_id, e)
        return "⚠️ Error al actualizar la conversación. Intenta de nuevo."


async def _cmd_estado(conv_id: str, tenant_id: str) -> str:
    if not conv_id:
        return "⚠️ Uso: <code>/estado {conversation_id}</code>"

    conv_id = conv_id.strip()
    supabase = _get_service_client()

    try:
        # A6.2.7: filtrar por tenant del operador → no leer customer_phone (PII)
        # de conversación de otro tenant.
        res = (
            supabase.table("conversations")
            .select("id, status, customer_phone, last_interaction_at")
            .eq("id", conv_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        conv = (res.data or [None])[0]
        if not conv:
            return f"❌ Conversación <code>{html.escape(conv_id[:8])}</code> no encontrada."

        status = conv.get("status", "N/D")
        phone = conv.get("customer_phone", "N/D")
        last_ts = str(conv.get("last_interaction_at") or "")[:16].replace("T", " ")

        status_icon = {"bot_active": "🤖", "human_takeover": "👤", "closed": "🔒"}.get(status, "❓")
        return (
            f"{status_icon} <b>Conversación</b> <code>{html.escape(conv_id[:8])}</code>\n"
            f"Estado: <b>{html.escape(str(status))}</b>\n"
            f"Cliente: {html.escape(str(phone))}\n"
            f"Última interacción: {html.escape(last_ts)} UTC"
        )
    except Exception as e:
        logger.error("[TG_WH] Error en /estado conv=%s: %s", conv_id, e)
        return "⚠️ Error al consultar la conversación."


def _send_telegram_reply(chat_id: int, text: str, tenant_id: str) -> None:
    """
    Envía respuesta al asesor en Telegram usando el bot_token del tenant
    propietario del chat_id.

    A6.2.7 finiquito 2026-06-24 — el `tenant_id` ya viene resuelto del chat_id
    en `telegram_webhook` (vía tenant_provider_identity). ELIMINADO el fallback
    legacy "primer tenant activo" que causaba cross-talk silencioso (MA-10): el
    handler ya rechaza chats no mapeados ANTES de llegar acá, así que siempre
    tenemos el tenant correcto. La config se busca SIEMPRE filtrada por tenant.

    Track 6: parse_mode HTML (los builders escapan el contenido dinámico).
    """
    supabase = _get_service_client()
    try:
        # Camino único: config del tenant resuelto (sin fallback cross-tenant).
        token = _resolve_bot_token(supabase, tenant_id)
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
                    "parse_mode": "HTML",
                },
            )
    except Exception as e:
        logger.error("[TG_WH] Error enviando respuesta Telegram chat=%s: %s", chat_id, e)
