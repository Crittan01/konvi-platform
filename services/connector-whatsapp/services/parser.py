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
                messages = value.get("messages", []) or []
                for msg in messages:
                    customer_phone = msg.get("from")
                    message_id = msg.get("id")
                    msg_type = msg.get("type", "text")
                    content = _extract_message_content(msg, msg_type)
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
                            "meta_message_id": message_id,
                            "content_type": msg_type,
                            "content": content,
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
