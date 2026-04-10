"""
WhatsApp Sender — envío de mensajes de texto vía Meta Graph API.

Usado por el endpoint de respuesta de agente humano en conversations.py.

Nota: Usa META_ACCESS_TOKEN y WHATSAPP_PHONE_ID del entorno.
En el futuro multi-WABA, estos valores vendrán de la tabla `tenants`
por tenant_id (una cuenta WABA por tenant).
"""
import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

REQUEST_TIMEOUT_SECONDS = 10


async def send_whatsapp_text(to_phone: str, text: str) -> Optional[str]:
    """
    Envía un mensaje de texto por WhatsApp Cloud API.

    Args:
        to_phone: Número del destinatario en formato E.164 sin '+' (ej: 5491155554444)
        text: Texto a enviar

    Returns:
        meta_message_id si el mensaje fue aceptado, None si hubo error.
    """
    if not META_ACCESS_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error(
            "Faltan META_ACCESS_TOKEN o WHATSAPP_PHONE_ID. "
            "Configura estas variables de entorno en el servicio api."
        )
        return None

    clean_phone = to_phone.lstrip("+").replace(" ", "").replace("-", "")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text,
        },
    }

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    url = f"{META_BASE_URL}/{WHATSAPP_PHONE_ID}/messages"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            resp_data = response.json()
            meta_message_id = resp_data.get("messages", [{}])[0].get("id", "unknown")
            logger.info(
                "[META API] Mensaje de agente enviado | to=%s | id=%s",
                clean_phone, meta_message_id,
            )
            return meta_message_id
        else:
            logger.error(
                "[META API] Error al enviar mensaje de agente | status=%s | body=%s",
                response.status_code, response.text,
            )
            return None

    except httpx.TimeoutException:
        logger.error("[META API] Timeout al enviar mensaje a %s", clean_phone)
        return None
    except Exception as e:
        logger.error("[META API] Error inesperado: %s", e, exc_info=True)
        return None
