import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

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
        
        # Extracción segura cruda del texto si existe
        content = ""
        if msg_type == "text":
            content = msg.get("text", {}).get("body", "")
        # Podremos agregar imágenes aquí después
        elif msg_type == "image":
            content = "[Imagen recibida]"
            
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
