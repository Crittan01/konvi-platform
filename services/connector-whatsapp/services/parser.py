import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


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
        return "[Mensaje interactivo recibido]"
    if msg_type == "button":
        return "[Respuesta de botón recibida]"
    return f"[Mensaje {msg_type} recibido]"


def parse_webhook_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Desempaca el infame y anidado JSON de WhatsApp Cloud API de forma defensiva.
    Si el payload no es un mensaje entrante (ej. Status update de envío o ping),
    retorna None sin causar crashes.
    """
    try:
        # 1. Aseguramos que es un objeto de WA Business
        if payload.get("object") != "whatsapp_business_account":
            return None
            
        entries = payload.get("entry", [])
        if not entries:
            return None
            
        entry = entries[0]
        waba_account_id = entry.get("id") # Este es el id nivel Meta
        
        changes = entry.get("changes", [])
        if not changes:
            return None
            
        value = changes[0].get("value", {})
        
        # Ocurre un evento de mensaje entrante si existe la llave "messages"
        messages = value.get("messages", [])
        if not messages:
            # Puede ser una lectura, entrega, o update. 
            # (Lo ignoramos para esta prueba fundacional Mv0)
            return None
            
        msg = messages[0]
        metadata = value.get("metadata", {})
        
        # Data Vital para Postgres
        phone_number_id = metadata.get("phone_number_id") 
        customer_phone = msg.get("from")
        message_id = msg.get("id")
        msg_type = msg.get("type", "text")
        
        # Contenido normalizado para almacenar en Inbox
        content = _extract_message_content(msg, msg_type)
            
        return {
            "meta_waba_id": waba_account_id,
            "destination_phone_id": phone_number_id,
            "customer_phone": customer_phone,
            "meta_message_id": message_id,
            "content_type": msg_type,
            "content": content
        }
        
    except Exception as e:
        logger.error(f"Error parseando dict de WhatsApp: {e}")
        return None
