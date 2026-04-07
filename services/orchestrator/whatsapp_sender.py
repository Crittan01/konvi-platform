import os
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Es el token permanente o de test que Meta te provee para ENVIAR mensajes (Distinto al Verify Token)
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

# Usaremos la version estable v18.0 o la que Meta indique actualmente
GRAPH_API_VERSION = "v18.0"

async def send_whatsapp_message(destination_phone: str, phone_number_id: str, text_content: str) -> bool:
    """
    Se comunica nativamente con los servidores de WhatsApp Cloud API para
    despachar un mensaje saliente de texto.
    """
    if not META_ACCESS_TOKEN:
        logger.error("No se puede enviar WPP: Falta META_ACCESS_TOKEN en el entorno.")
        return False
        
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": destination_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text_content
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            
        if response.status_code in (200, 201):
            logger.info(f"Mensaje saliente exitoso enviado a {destination_phone}")
            return True
        else:
            logger.error(f"Fallo al enviar mensaje a Graph API HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error critico de red comunicando con Graph API: {e}")
        return False
