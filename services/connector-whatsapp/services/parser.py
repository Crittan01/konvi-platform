import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _extract_interactive_payload(msg: Dict[str, Any]) -> Dict[str, Any]:
    interactive = msg.get("interactive", {}) or {}
    result: Dict[str, Any] = {}
    if "button_reply" in interactive:
        button_reply = interactive.get("button_reply", {}) or {}
        result["kind"] = "button_reply"
        result["id"] = button_reply.get("id")
        result["title"] = button_reply.get("title")
    elif "list_reply" in interactive:
        list_reply = interactive.get("list_reply", {}) or {}
        result["kind"] = "list_reply"
        result["id"] = list_reply.get("id")
        result["title"] = list_reply.get("title")
        result["description"] = list_reply.get("description")
    elif "nfm_reply" in interactive:
        nfm_reply = interactive.get("nfm_reply", {}) or {}
        result["kind"] = "nfm_reply"
        result["name"] = nfm_reply.get("name")
        result["body"] = nfm_reply.get("body")
        result["response_json"] = nfm_reply.get("response_json")
    return {k: v for k, v in result.items() if v is not None}


def _extract_media_metadata(msg: Dict[str, Any], msg_type: str) -> Dict[str, Optional[str]]:
    """Extrae media_id y mime_type de mensajes media de Meta.

    Estos campos son necesarios para que el orquestador pueda descargar el
    media y enviarlo a Gemini multimodal (audio).
    """
    if msg_type not in {"audio", "image", "video", "document", "sticker"}:
        return {"media_id": None, "media_mime": None}
    media_obj = msg.get(msg_type, {}) or {}
    return {
        "media_id": media_obj.get("id"),
        "media_mime": media_obj.get("mime_type"),
    }


def _extract_message_content(msg: Dict[str, Any], msg_type: str) -> str:
    """Retorna contenido legible para Inbox, incluso en mensajes no-texto."""
    if msg_type == "text":
        return msg.get("text", {}).get("body", "")
    if msg_type == "image":
        caption = (msg.get("image", {}) or {}).get("caption", "").strip()
        return f"[Imagen recibida] {caption}".strip()
    if msg_type == "audio":
        return "[Audio recibido]"
    if msg_type == "video":
        caption = (msg.get("video", {}) or {}).get("caption", "").strip()
        return f"[Video recibido] {caption}".strip()
    if msg_type == "document":
        filename = (msg.get("document", {}) or {}).get("filename", "").strip()
        return f"[Documento recibido] {filename}".strip()
    if msg_type == "sticker":
        return "[Sticker recibido]"
    if msg_type == "location":
        return "[Ubicación recibida]"
    if msg_type == "interactive":
        interactive = _extract_interactive_payload(msg)
        kind = interactive.get("kind")
        title = interactive.get("title")
        option_id = interactive.get("id")
        if kind == "button_reply":
            return f"[Botón] {title or option_id or 'sin detalle'}"
        if kind == "list_reply":
            return f"[Lista] {title or option_id or 'sin detalle'}"
        if kind == "nfm_reply":
            return "[Formulario interactivo recibido]"
        return "[Mensaje interactivo recibido]"
    if msg_type == "button":
        button = msg.get("button", {}) or {}
        button_text = button.get("text") or button.get("payload")
        return f"[Respuesta de botón] {button_text or 'sin detalle'}"
    return f"[Mensaje {msg_type} recibido]"


def parse_webhook_payloads(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """
    Desempaca el infame y anidado JSON de WhatsApp Cloud API de forma defensiva.
    Retorna lista de mensajes entrantes parseados.
    Si no hay mensajes entrantes (status updates, pings, etc), retorna lista vacía.
    """
    try:
        # 1. Aseguramos que es un objeto de WA Business
        if payload.get("object") != "whatsapp_business_account":
            return []

        entries = payload.get("entry", [])
        if not entries:
            return []

        parsed_messages: list[Dict[str, Any]] = []
        for entry in entries:
            waba_account_id = entry.get("id")  # Este es el id nivel Meta
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {}) or {}
                metadata = value.get("metadata", {}) or {}
                phone_number_id = metadata.get("phone_number_id")
                # F2 2026-07-04 — Meta envía `value.contacts[]` con el nombre de
                # perfil del cliente: [{profile: {name}, wa_id}]. Lo indexamos por
                # wa_id para denormalizar `conversations.contact_name` (sólo-display).
                contacts = value.get("contacts", []) or []
                name_by_wa_id: Dict[str, str] = {}
                for contact in contacts:
                    wa_id = contact.get("wa_id")
                    profile = contact.get("profile", {}) or {}
                    profile_name = (profile.get("name") or "").strip()
                    if wa_id and profile_name:
                        name_by_wa_id[wa_id] = profile_name
                messages = value.get("messages", []) or []
                for msg in messages:
                    customer_phone = msg.get("from")
                    message_id = msg.get("id")
                    msg_type = msg.get("type", "text")
                    content = _extract_message_content(msg, msg_type)
                    media_meta = _extract_media_metadata(msg, msg_type)
                    msg_context = msg.get("context", {}) or {}
                    parsed_payload = {
                        "timestamp": msg.get("timestamp"),
                        "context": {
                            "id": msg_context.get("id"),
                            "from": msg_context.get("from"),
                        },
                        "interactive": _extract_interactive_payload(msg) if msg_type == "interactive" else {},
                        "button": (msg.get("button", {}) or {}) if msg_type == "button" else {},
                    }
                    parsed_payload = {k: v for k, v in parsed_payload.items() if v}

                    parsed_messages.append(
                        {
                            "meta_waba_id": waba_account_id,
                            "destination_phone_id": phone_number_id,
                            "customer_phone": customer_phone,
                            # F2 — nombre de perfil Meta (si vino en contacts[]).
                            "customer_name": name_by_wa_id.get(customer_phone),
                            "meta_message_id": message_id,
                            "content_type": msg_type,
                            "content": content,
                            "media_id": media_meta["media_id"],
                            "media_mime": media_meta["media_mime"],
                            "payload": parsed_payload,
                        }
                    )
        return parsed_messages
    except Exception as e:
        logger.error(f"Error parseando dict de WhatsApp: {e}")
        return []


def parse_webhook_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compat legacy: retorna solo el primer mensaje parseado o None."""
    parsed = parse_webhook_payloads(payload)
    return parsed[0] if parsed else None


# ─── Sem 6 pre-HSM (rev. 106 / 2026-05-08) — Multi-field dispatcher ──────────
#
# Meta envía un POST con `entry[].changes[]`. Cada `change` tiene un `field`
# que discrimina el tipo de evento. Hasta rev. 105 sólo procesábamos el field
# "messages". A partir de F2 HSM templates necesitamos:
#
#   - "messages" + statuses[]    → delivery receipts (delivered_at, read_at,
#                                   failed_code, pricing.category, etc.)
#   - "message_template_status_update"
#                                → template aprobado/rechazado/pausado
#   - "message_template_quality_update"
#                                → quality YELLOW/RED de un template
#   - "phone_number_quality_update"
#                                → quality del WABA phone (signal early)
#   - "account_alerts" / "account_review_update"
#                                → alertas comerciales/operativas
#
# Esta función NO ejecuta side-effects — devuelve eventos tipados. Los
# handlers downstream (DB persistence per tipo) viven en `template_events.py`:
#   - template/phone status/quality → `whatsapp_templates` / `tenant_integrations`.
#   - outbound_status (delivery receipt) → columnas de entrega en `messages`
#     (`delivery_status`/`delivered_at`/`read_at`/`failed_at`/`delivery_error`/
#     pricing), NO una tabla `whatsapp_status_events` aparte: el receipt pertenece
#     a la fila del mensaje ya persistido (match por meta_message_id UNIQUE), lo
#     que da idempotencia por avance monótono y lo hace visible directo en Inbox.
#     Ver migración `20260704000000_messages_delivery_receipts.sql`.


# Tipos canónicos del dispatcher. Strings (no enum) para serialización
# directa en el log / pgmq message.
EVENT_TYPE_INBOUND_MESSAGE = "inbound_message"
EVENT_TYPE_OUTBOUND_STATUS = "outbound_status"
EVENT_TYPE_TEMPLATE_STATUS_UPDATE = "template_status_update"
EVENT_TYPE_TEMPLATE_QUALITY_UPDATE = "template_quality_update"
EVENT_TYPE_PHONE_QUALITY_UPDATE = "phone_quality_update"
EVENT_TYPE_ACCOUNT_ALERT = "account_alert"
EVENT_TYPE_UNKNOWN = "unknown"


def _classify_change(field: str, value: Dict[str, Any]) -> str:
    """Clasifica el tipo de evento según `change.field` + presencia de
    sub-objetos típicos."""
    if field == "messages":
        # El field "messages" puede traer messages[] (inbound) Y statuses[]
        # (outbound). Si statuses está presente Y messages NO, es status puro;
        # si messages presente, es inbound (statuses pueden ser secundarios
        # — tratarlos en handler downstream).
        if value.get("messages"):
            return EVENT_TYPE_INBOUND_MESSAGE
        if value.get("statuses"):
            return EVENT_TYPE_OUTBOUND_STATUS
        return EVENT_TYPE_UNKNOWN
    if field == "message_template_status_update":
        return EVENT_TYPE_TEMPLATE_STATUS_UPDATE
    if field == "message_template_quality_update":
        return EVENT_TYPE_TEMPLATE_QUALITY_UPDATE
    if field == "phone_number_quality_update":
        return EVENT_TYPE_PHONE_QUALITY_UPDATE
    if field in ("account_alerts", "account_review_update", "account_update"):
        return EVENT_TYPE_ACCOUNT_ALERT
    return EVENT_TYPE_UNKNOWN


def _parse_status_event(
    waba_account_id: str,
    phone_number_id: str,
    status: Dict[str, Any],
) -> Dict[str, Any]:
    """Mapea un item de `value.statuses[]` a evento normalizado."""
    pricing = status.get("pricing") or {}
    return {
        "event_type": EVENT_TYPE_OUTBOUND_STATUS,
        "meta_waba_id": waba_account_id,
        "destination_phone_id": phone_number_id,
        "meta_message_id": status.get("id"),
        "recipient_phone": status.get("recipient_id"),
        "status": status.get("status"),  # 'sent' | 'delivered' | 'read' | 'failed'
        "timestamp": status.get("timestamp"),
        "conversation_id": (status.get("conversation") or {}).get("id"),
        "conversation_origin": (status.get("conversation") or {}).get("origin", {}).get("type"),
        "pricing_category": pricing.get("category"),  # 'utility' | 'marketing' | 'authentication' | 'service'
        "pricing_billable": pricing.get("billable"),
        "pricing_model": pricing.get("pricing_model"),
        "errors": status.get("errors") or [],  # [{code, title, message}]
    }


def _parse_template_status_update(
    waba_account_id: str,
    value: Dict[str, Any],
) -> Dict[str, Any]:
    """Field message_template_status_update — envía cuando un template
    cambia de estado en review Meta (PENDING → APPROVED/REJECTED/PAUSED/DISABLED).

    Schema verificado per dossier sec. 2 + Meta docs:
      {message_template_id, message_template_name, message_template_language,
       event, reason, ...}
    """
    return {
        "event_type": EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
        "meta_waba_id": waba_account_id,
        "meta_template_id": value.get("message_template_id"),
        "template_name": value.get("message_template_name"),
        "template_language": value.get("message_template_language"),
        "new_status": value.get("event"),  # APPROVED|REJECTED|PENDING|PAUSED|DISABLED|FLAGGED|LIMIT_EXCEEDED
        "reason": value.get("reason"),
    }


def _parse_template_quality_update(
    waba_account_id: str,
    value: Dict[str, Any],
) -> Dict[str, Any]:
    """Field message_template_quality_update — quality YELLOW/RED de template.

    Schema:
      {message_template_id, message_template_name, message_template_language,
       previous_quality_score, new_quality_score}
    """
    return {
        "event_type": EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
        "meta_waba_id": waba_account_id,
        "meta_template_id": value.get("message_template_id"),
        "template_name": value.get("message_template_name"),
        "template_language": value.get("message_template_language"),
        "previous_quality": value.get("previous_quality_score"),  # GREEN|YELLOW|RED
        "new_quality": value.get("new_quality_score"),
    }


def _parse_phone_quality_update(
    waba_account_id: str,
    value: Dict[str, Any],
) -> Dict[str, Any]:
    """Field phone_number_quality_update — quality del phone (GREEN/YELLOW/RED).

    Schema:
      {display_phone_number, current_limit, event}
    """
    return {
        "event_type": EVENT_TYPE_PHONE_QUALITY_UPDATE,
        "meta_waba_id": waba_account_id,
        "display_phone_number": value.get("display_phone_number"),
        "current_limit": value.get("current_limit"),  # tier: TIER_50|TIER_250|TIER_1K|TIER_10K|TIER_100K|TIER_UNLIMITED
        "event": value.get("event"),  # FLAGGED|UNFLAGGED|UPGRADED|DOWNGRADED|...
    }


def _parse_account_alert(
    waba_account_id: str,
    field: str,
    value: Dict[str, Any],
) -> Dict[str, Any]:
    """Catch-all para account_alerts, account_review_update, account_update."""
    return {
        "event_type": EVENT_TYPE_ACCOUNT_ALERT,
        "meta_waba_id": waba_account_id,
        "field": field,  # preservar field original para handler ops
        "raw_value": value,  # log completo — caller decide qué hacer
    }


def parse_webhook_events(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Multi-field dispatcher: clasifica TODOS los `change.field` del payload.

    Para `field="messages"`:
      - Si tiene `messages[]` (inbound): NO incluido aquí — usar
        `parse_webhook_payloads()` (legacy, downstream `db_persistence`).
      - Si tiene `statuses[]` (outbound delivery): incluido como `outbound_status`.

    Para fields no-messages:
      - Cada change emite UN evento normalizado.

    Retorna lista vacía si payload no tiene fields procesables.

    Diseño F2 HSM: el caller (typically `decouple_and_enqueue` extendido)
    invoca AMBAS funciones — `parse_webhook_payloads` para inbound y
    `parse_webhook_events` para el resto. Backward compat preservado.
    """
    try:
        if payload.get("object") != "whatsapp_business_account":
            return []
        entries = payload.get("entry") or []
        if not entries:
            return []

        events: list[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            waba_account_id = entry.get("id") or ""
            changes = entry.get("changes") or []
            for change in changes:
                if not isinstance(change, dict):
                    continue
                field = (change.get("field") or "").strip()
                value = change.get("value") or {}
                if not isinstance(value, dict):
                    continue

                event_type = _classify_change(field, value)

                if event_type == EVENT_TYPE_INBOUND_MESSAGE:
                    # Inbound queda en parse_webhook_payloads — no duplicar.
                    continue

                if event_type == EVENT_TYPE_OUTBOUND_STATUS:
                    metadata = value.get("metadata") or {}
                    phone_number_id = metadata.get("phone_number_id") or ""
                    statuses = value.get("statuses") or []
                    for status in statuses:
                        if isinstance(status, dict):
                            events.append(_parse_status_event(
                                waba_account_id, phone_number_id, status,
                            ))

                elif event_type == EVENT_TYPE_TEMPLATE_STATUS_UPDATE:
                    events.append(_parse_template_status_update(waba_account_id, value))

                elif event_type == EVENT_TYPE_TEMPLATE_QUALITY_UPDATE:
                    events.append(_parse_template_quality_update(waba_account_id, value))

                elif event_type == EVENT_TYPE_PHONE_QUALITY_UPDATE:
                    events.append(_parse_phone_quality_update(waba_account_id, value))

                elif event_type == EVENT_TYPE_ACCOUNT_ALERT:
                    events.append(_parse_account_alert(waba_account_id, field, value))

                else:
                    logger.debug(
                        "[WH_DISPATCH] field desconocido ignorado: %r", field,
                    )
        return events
    except Exception as e:
        logger.error("[WH_DISPATCH] error procesando webhook events: %s", e)
        return []
