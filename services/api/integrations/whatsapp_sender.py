import logging
from typing import Optional, Any
import httpx

logger = logging.getLogger(__name__)

META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

REQUEST_TIMEOUT_SECONDS = 10


def _get_tenant_wa_credentials(tenant_id: str, supabase: Any) -> tuple[str, str]:
    """
    Returns (phone_number_id, access_token) only when WhatsApp is connected
    for the tenant in tenant_integrations.
    """
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .single()
            .execute()
        )
        if not res.data:
            return "", ""
        if res.data.get("status") != "connected":
            return "", ""
        creds = res.data.get("credentials", {})
        return creds.get("phone_number_id", ""), creds.get("access_token", "")
    except Exception:
        return "", ""


async def send_whatsapp_text(
    to_phone: str,
    text: str,
    tenant_id: str = "",
    supabase: Optional[Any] = None,
) -> Optional[str]:
    phone_id = ""
    access_token = ""
    if tenant_id and supabase:
        phone_id, access_token = _get_tenant_wa_credentials(tenant_id, supabase)

    if not phone_id or not access_token:
        logger.error(
            "Faltan credenciales WhatsApp conectadas en tenant_integrations para tenant=%s",
            tenant_id or "unknown",
        )
        return None

    clean_phone = to_phone.lstrip("+").replace(" ", "").replace("-", "")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{META_BASE_URL}/{phone_id}/messages"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            meta_message_id = response.json().get("messages", [{}])[0].get("id", "unknown")
            logger.info("[META API] Mensaje enviado | to=%s | id=%s", clean_phone, meta_message_id)
            return meta_message_id
        else:
            logger.error("[META API] Error | status=%s | body=%s", response.status_code, response.text)
            return None

    except httpx.TimeoutException:
        logger.error("[META API] Timeout al enviar a %s", clean_phone)
        return None
    except Exception as e:
        logger.error("[META API] Error inesperado: %s", e, exc_info=True)
        return None
