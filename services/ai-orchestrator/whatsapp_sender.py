import logging
import os
import httpx
from supabase import Client

logger = logging.getLogger("orchestrator.whatsapp_sender")

META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

# Timeout razonable — Meta Graph API suele responder en < 2s
REQUEST_TIMEOUT_SECONDS = 10


async def send_whatsapp_message(
    tenant_id: str,
    supabase: Client,
    to_phone: str,
    text: str,
) -> bool:
    """
    Envía un mensaje de texto por WhatsApp Cloud API (Meta Graph API).

    IMPORTANTE: En producción, cada tenant tendrá su propio PHONE_ID y ACCESS_TOKEN
    configurados en la tabla 'tenants'. Por ahora se usa la config de env (single-WABA).

    Args:
        tenant_id: UUID del tenant (para futura expansión multi-WABA)
        supabase: Cliente de Supabase (para obtener config del tenant en el futuro)
        to_phone: Número del destinatario en formato internacional (ej: 5491155554444)
        text: Texto del mensaje a enviar

    Returns:
        True si el mensaje fue aceptado por Meta, False si hubo error.
    """
    if not META_ACCESS_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error(
            "Faltan META_ACCESS_TOKEN o WHATSAPP_PHONE_ID. "
            "Configura estas variables en el entorno."
        )
        return False

    # Normalizar número: asegurar que no tiene el prefijo '+'
    # Meta acepta formato E.164 sin el '+'
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
            message_id = resp_data.get("messages", [{}])[0].get("id", "unknown")
            logger.info(
                f"[META API] Mensaje enviado exitosamente | "
                f"to={clean_phone} | meta_message_id={message_id}"
            )
            return True
        else:
            logger.error(
                f"[META API] Error al enviar mensaje | "
                f"status={response.status_code} | body={response.text}"
            )
            return False

    except httpx.TimeoutException:
        logger.error(f"[META API] Timeout al enviar mensaje a {clean_phone}")
        return False
    except Exception as e:
        logger.error(f"[META API] Error inesperado: {e}", exc_info=True)
        return False
