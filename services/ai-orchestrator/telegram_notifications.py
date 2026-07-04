"""Notificaciones Telegram a operador del tenant (escalations).

Rev. 109 producción — usado por dispatcher.py + agentic/tools/escalation.py
+ agentic/tools/claims.py + worker.py (SLA tracker) para alertar al
operador humano.

Rev. 109 founder 2026-05-28 — UNIFICACIÓN de fuentes (canal único):
  ANTES: 2 fuentes paralelas de "dónde notificar":
    • path A — `tenant_integrations.provider='telegram'` (este archivo).
    • path B — `notification_settings.channel='telegram'`
      (`notifications.dispatch_human_takeover_event`).
  Riesgo: tenant podía configurar solo path A → este código funcionaba,
  pero el worker (path B) NO encontraba → desincronía silenciosa. Y al
  revés: KAIU tiene solo path B → este código fallaba silent.

  AHORA: `notification_settings` es ÚNICA fuente de verdad.
  `notify_escalation_async` lee de `notification_settings` (mismo patrón
  que `dispatch_human_takeover_event` en `notifications.py:286`).
  Cero duplicación de configuración entre tablas.

Compat: si tenant NO tiene rows en `notification_settings`, retorna
False silent (sin error). Operador configura via UI Settings → Canales.

NO duplica lógica de `notifications.py` — usa `_send_telegram_notification`
del mismo módulo. Diferencia: `dispatch_human_takeover_event` consume
eventos pgmq async; `notify_escalation_async` es invocación inline desde
un tool (path directo + path B sigue activo en paralelo como respaldo).
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

    Fuente única: `notification_settings` (channel='telegram', enabled=true).
    Resolución bot_token vía Vault (config.bot_token o token_preview).

    Args:
        supabase: cliente DB.
        tenant_id: para resolver bot_token + chat_id del tenant.
        conversation_id: contexto opcional (incluido en el mensaje).
        reason: texto descriptivo de la escalación (multilinea OK).
        severity: 'info' | 'warning' | 'critical' (afecta emoji prefijo).

    Returns:
        True si Telegram aceptó el mensaje, False si fallo (canal sin
        configurar, error HTTP, etc.).
    """
    if not reason:
        return False

    # Fuente única: notification_settings.
    try:
        res = (
            supabase.table("notification_settings")
            .select("channel, enabled, config")
            .eq("tenant_id", tenant_id)
            .eq("enabled", True)
            .eq("channel", "telegram")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.info(
            "[TG_ESCALATION] tenant=%s lookup notification_settings falló: %s",
            tenant_id, exc,
        )
        return False

    rows = getattr(res, "data", None) or []
    if not rows:
        logger.info(
            "[TG_ESCALATION] tenant=%s sin canal telegram en notification_settings — "
            "configurar en Console → Integraciones → Telegram",
            tenant_id[:8] if tenant_id else "?",
        )
        return False

    config_row = dict(rows[0].get("config") or {})
    chat_id = config_row.get("chat_id") or config_row.get("telegram_chat_id")
    if not chat_id:
        logger.info(
            "[TG_ESCALATION] tenant=%s notification_settings sin chat_id",
            tenant_id[:8] if tenant_id else "?",
        )
        return False

    # Auto-vincula (tenant, telegram, chat_id) — misma razón que en
    # dispatch_human_takeover_event: mantiene vivos /resolver /estado desde este
    # chat. Best-effort (nunca rompe la escalación). Reusa el helper único de
    # notifications.py para no duplicar la lógica del registry.
    try:
        from notifications import _register_telegram_identity  # noqa: PLC0415
        _register_telegram_identity(supabase, tenant_id, chat_id)
    except Exception as exc:
        logger.debug("[TG_ESCALATION] auto-link skip tenant=%s: %s", tenant_id, exc)

    # Resolver bot_token via Vault (mismo patrón que dispatch_human_takeover_event).
    try:
        from vault_helper import VaultHelper, resolve_secret
        vault = VaultHelper(supabase)
        bot_token = resolve_secret(vault, config_row, "bot_token") or ""
    except Exception as exc:
        logger.warning(
            "[TG_ESCALATION] tenant=%s no pudo resolver bot_token: %s",
            tenant_id, exc,
        )
        return False
    if not bot_token:
        logger.warning(
            "[TG_ESCALATION] tenant=%s bot_token vacío post-Vault — verificar credencial",
            tenant_id[:8] if tenant_id else "?",
        )
        return False

    prefix = {
        "info": "ℹ️", "warning": "⚠️", "critical": "🚨",
    }.get(severity, "⚠️")
    convo_suffix = (
        f"\n\n_Conv: {conversation_id[:8]}_" if conversation_id else ""
    )
    text = f"{prefix} *Escalación*\n\n{reason}{convo_suffix}"

    # `_send_telegram_notification` espera keys `bot_token` y `chat_id`
    # (NO `telegram_bot_token` / `telegram_chat_id` — bug histórico de
    # path A pre-rev109 que silenciaba el envío). Verificado contra
    # `notifications.py:46-79` (single source of HTTP client).
    config = {"bot_token": bot_token, "chat_id": chat_id}
    try:
        from notifications import _send_telegram_notification
        return await _send_telegram_notification(config, text)
    except Exception as exc:
        logger.warning(
            "[TG_ESCALATION] send falló tenant=%s: %s", tenant_id, exc,
        )
        return False
