"""Handlers DB persistence para eventos webhook de templates Meta.

Sem 7 F2 item 4 (rev. 106 / 2026-05-17).

El parser dispatcher (Sem 6, `parser.py:parse_webhook_events`) ya clasifica
eventos por `change.field`. Este módulo persiste los relevantes a HSM:

  - `EVENT_TYPE_TEMPLATE_STATUS_UPDATE` → update `whatsapp_templates.status`
  - `EVENT_TYPE_TEMPLATE_QUALITY_UPDATE` → update `whatsapp_templates.quality_rating`
  - `EVENT_TYPE_PHONE_QUALITY_UPDATE` → update `tenant_integrations.credentials.tier`

Los handlers son **idempotentes y tolerantes a fallos**:
  - Si el template no existe en Konvi DB (caso edge: tenant creó template
    via API Meta directamente sin pasar por Konvi) → WARN + skip.
  - Si la conexión a DB falla → log error pero NO levanta — webhook
    Meta debe responder 200 OK aunque internamente falle.

NO usa el helper `services/api/lib/whatsapp_templates.py` por isolation
deploy unit (connector-whatsapp tiene rootDir distinto en Render). En su
lugar lookup directo a tabla con service_role (bypass RLS, requiere
filtrado explícito por waba_id/tenant_id).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.db_persistence import get_supabase, _resolve_tenant_by_waba

logger = logging.getLogger(__name__)


# Estados/quality canónicos (mismo set que whatsapp_templates.py canonical)
VALID_TEMPLATE_STATUSES = frozenset({
    "LOCAL_DRAFT", "PENDING", "APPROVED", "REJECTED",
    "PAUSED", "DISABLED", "FLAGGED", "LIMIT_EXCEEDED",
})

VALID_QUALITY_RATINGS = frozenset({"GREEN", "YELLOW", "RED", "UNKNOWN"})


def persist_template_status_update(event: Dict[str, Any]) -> bool:
    """Recibe evento `EVENT_TYPE_TEMPLATE_STATUS_UPDATE` del parser y
    actualiza `whatsapp_templates.status` + `status_reason` + (si APPROVED)
    `approved_at`.

    Lookup por `meta_template_id` (campo más estable que name+lang).

    Args:
        event: dict emitido por `_parse_template_status_update`:
          {event_type, meta_waba_id, meta_template_id, template_name,
           template_language, new_status, reason}

    Returns:
        True si actualizó al menos 1 fila, False si template no encontrado.
        NO levanta excepciones — log + return False para fallos silenciosos.
    """
    meta_template_id = (event or {}).get("meta_template_id")
    new_status = (event or {}).get("new_status")

    if not meta_template_id or not new_status:
        logger.error(
            "[WA_TPL_STATUS] evento inválido (falta meta_template_id o new_status): %s",
            event,
        )
        return False

    new_status = str(new_status).strip().upper()
    if new_status not in VALID_TEMPLATE_STATUSES:
        logger.warning(
            "[WA_TPL_STATUS] new_status %r no canónico — persistido tal cual "
            "(Meta puede haber agregado nuevos estados; CHECK constraint DB rechazará)",
            new_status,
        )

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[WA_TPL_STATUS] no se pudo obtener supabase client: %s", exc)
        return False

    update_fields: Dict[str, Any] = {
        "status": new_status,
        "status_reason": event.get("reason"),
    }
    if new_status == "APPROVED":
        update_fields["approved_at"] = datetime.now(timezone.utc).isoformat()

    try:
        res = (
            sb.table("whatsapp_templates")
            .update(update_fields)
            .eq("meta_template_id", str(meta_template_id))
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[WA_TPL_STATUS] meta_template_id=%s no matchea ningún row en "
                "whatsapp_templates — template puede haberse creado fuera de "
                "Konvi (via API Meta directa). Omitiendo. event_name=%s",
                meta_template_id, event.get("template_name"),
            )
            return False
        logger.info(
            "[WA_TPL_STATUS] template actualizado meta_id=%s name=%s new_status=%s reason=%s",
            meta_template_id, event.get("template_name"), new_status,
            event.get("reason"),
        )
        return True
    except Exception as exc:
        logger.error(
            "[WA_TPL_STATUS] error UPDATE whatsapp_templates meta_id=%s: %s",
            meta_template_id, exc,
        )
        return False


def persist_template_quality_update(event: Dict[str, Any]) -> bool:
    """Recibe evento `EVENT_TYPE_TEMPLATE_QUALITY_UPDATE` y actualiza
    `whatsapp_templates.quality_rating`.

    Args:
        event: dict {event_type, meta_waba_id, meta_template_id, template_name,
                     template_language, previous_quality, new_quality}

    Returns:
        True si update OK, False si no matchea.
    """
    meta_template_id = (event or {}).get("meta_template_id")
    new_quality = (event or {}).get("new_quality")

    if not meta_template_id or not new_quality:
        logger.error(
            "[WA_TPL_QUALITY] evento inválido: %s", event,
        )
        return False

    new_quality = str(new_quality).strip().upper()
    if new_quality not in VALID_QUALITY_RATINGS:
        logger.warning(
            "[WA_TPL_QUALITY] new_quality %r no canónico — Meta puede haber "
            "agregado nuevos valores",
            new_quality,
        )

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[WA_TPL_QUALITY] no se pudo obtener supabase: %s", exc)
        return False

    try:
        res = (
            sb.table("whatsapp_templates")
            .update({"quality_rating": new_quality})
            .eq("meta_template_id", str(meta_template_id))
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[WA_TPL_QUALITY] meta_template_id=%s no encontrado en DB. event_name=%s",
                meta_template_id, event.get("template_name"),
            )
            return False
        logger.info(
            "[WA_TPL_QUALITY] template quality actualizado meta_id=%s name=%s "
            "previous=%s new=%s",
            meta_template_id, event.get("template_name"),
            event.get("previous_quality"), new_quality,
        )
        return True
    except Exception as exc:
        logger.error(
            "[WA_TPL_QUALITY] error UPDATE meta_id=%s: %s",
            meta_template_id, exc,
        )
        return False


def persist_phone_quality_update(event: Dict[str, Any]) -> bool:
    """Recibe evento `EVENT_TYPE_PHONE_QUALITY_UPDATE` (tier del phone+quality
    del WABA) y actualiza `tenant_integrations.credentials.tier`.

    El tier impacta cuántos unique recipients/24h podemos enviar templates
    MARKETING (250/1K/10K/100K/UNLIMITED).

    Args:
        event: dict {event_type, meta_waba_id, display_phone_number,
                     current_limit, event (UPGRADED|DOWNGRADED|FLAGGED|...)}

    Returns:
        True si update OK, False si tenant no resuelve o no hay current_limit.
    """
    meta_waba_id = (event or {}).get("meta_waba_id")
    current_limit = (event or {}).get("current_limit")
    event_type = (event or {}).get("event")

    if not meta_waba_id or not current_limit:
        logger.error(
            "[PHONE_QUALITY] evento inválido (falta meta_waba_id o current_limit): %s",
            event,
        )
        return False

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[PHONE_QUALITY] no se pudo obtener supabase: %s", exc)
        return False

    tenant_id = _resolve_tenant_by_waba(sb, meta_waba_id)
    if not tenant_id:
        logger.warning(
            "[PHONE_QUALITY] waba=%s no resuelve tenant. event=%s",
            meta_waba_id, event_type,
        )
        return False

    # Update tier en tenant_integrations.credentials JSONB.
    # JSONB partial update via SET credentials = credentials || jsonb_build_object()
    # PostgREST no soporta esa sintaxis nativa → leemos, mergeamos, escribimos.
    try:
        res = (
            sb.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[PHONE_QUALITY] tenant_integrations whatsapp no existe tenant=%s",
                tenant_id,
            )
            return False
        creds = (rows[0] or {}).get("credentials") or {}
        if not isinstance(creds, dict):
            creds = {}
        creds["tier"] = str(current_limit).strip().upper()
        # Si Meta envía evento FLAGGED/UNFLAGGED quality también queda registrado
        if event_type in ("FLAGGED", "UNFLAGGED"):
            creds["quality_signal"] = event_type

        sb.table("tenant_integrations").update({"credentials": creds}).eq(
            "tenant_id", tenant_id,
        ).eq("provider", "whatsapp").execute()

        logger.info(
            "[PHONE_QUALITY] tier actualizado tenant=%s waba=%s tier=%s event=%s",
            tenant_id, meta_waba_id, creds["tier"], event_type,
        )
        return True
    except Exception as exc:
        logger.error(
            "[PHONE_QUALITY] error UPDATE tenant=%s: %s", tenant_id, exc,
        )
        return False


def handle_event(event: Dict[str, Any]) -> Optional[bool]:
    """Dispatcher: rutea un evento al handler correspondiente según event_type.

    Args:
        event: dict emitido por `parser.parse_webhook_events`.

    Returns:
        - True si handler procesó OK
        - False si handler falló o template no encontrado
        - None si event_type no requiere persistence (logueo nomás)
    """
    if not isinstance(event, dict):
        return None
    event_type = event.get("event_type")

    # Lazy imports — evita circular si parser eventualmente importa este módulo
    from services.parser import (
        EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
        EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
        EVENT_TYPE_PHONE_QUALITY_UPDATE,
    )

    if event_type == EVENT_TYPE_TEMPLATE_STATUS_UPDATE:
        return persist_template_status_update(event)
    if event_type == EVENT_TYPE_TEMPLATE_QUALITY_UPDATE:
        return persist_template_quality_update(event)
    if event_type == EVENT_TYPE_PHONE_QUALITY_UPDATE:
        return persist_phone_quality_update(event)

    # outbound_status, account_alert, etc. → no persistence todavía (futuro Sem 11)
    return None
