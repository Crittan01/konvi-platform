import logging
from typing import Optional
import httpx
from supabase import Client

logger = logging.getLogger("orchestrator.whatsapp_sender")

META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

REQUEST_TIMEOUT_SECONDS = 10


def _get_tenant_wa_credentials(tenant_id: str, supabase: Client) -> tuple[str, str]:
    """
    Returns (phone_number_id, access_token) only when the tenant has
    WhatsApp status=connected in tenant_integrations.
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
        from vault_helper import VaultHelper, resolve_secret
        vault = VaultHelper(supabase)
        phone_id     = creds.get("phone_number_id", "")
        access_token = resolve_secret(vault, creds, "access_token") or ""
        return phone_id, access_token
    except Exception:
        return "", ""


async def send_whatsapp_message(
    tenant_id: str,
    supabase: Client,
    to_phone: str,
    text: Optional[str] = None,
    image_link: Optional[str] = None,
    image_caption: Optional[str] = None,
) -> Optional[str]:
    """Envía un mensaje WhatsApp al cliente.

    Modo TEXTO (default, backwards-compat): pasar `text`.
    Modo IMAGEN (F8.B): pasar `image_link` (URL HTTPS) y opcionalmente
    `image_caption`. Meta v21.0 exige HTTPS y MIME image/jpeg|png|webp.

    Si se pasan ambos, IMAGEN tiene prioridad — el caller debe enviar texto
    como mensaje separado si lo necesita.
    """
    phone_id, access_token = _get_tenant_wa_credentials(tenant_id, supabase)

    if not phone_id or not access_token:
        logger.error(
            "Faltan credenciales WhatsApp conectadas en tenant_integrations para tenant=%s",
            tenant_id,
        )
        return None

    clean_phone = to_phone.lstrip("+").replace(" ", "").replace("-", "")

    if image_link:
        # F8.B.1 — payload type=image. Meta exige link HTTPS público.
        if not image_link.startswith("https://"):
            logger.error(
                "[META API] image_link debe ser HTTPS (Meta v21.0 lo exige). Recibido=%s",
                image_link,
            )
            return None
        image_obj: dict = {"link": image_link}
        if image_caption:
            image_obj["caption"] = image_caption
        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": image_obj,
        }
        msg_kind = "image"
    elif text is not None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        msg_kind = "text"
    else:
        logger.error(
            "[META API] send_whatsapp_message requiere `text` o `image_link` para tenant=%s",
            tenant_id,
        )
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{META_BASE_URL}/{phone_id}/messages"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            message_id = response.json().get("messages", [{}])[0].get("id", "unknown")
            logger.info(
                "[META API] Mensaje enviado | type=%s | to=%s | meta_message_id=%s",
                msg_kind, clean_phone, message_id,
            )
            return message_id
        else:
            logger.error(
                "[META API] Error type=%s | status=%s | body=%s",
                msg_kind, response.status_code, response.text,
            )
            return None

    except httpx.TimeoutException:
        logger.error("[META API] Timeout al enviar a %s", clean_phone)
        return None
    except Exception as e:
        logger.error("[META API] Error inesperado: %s", e, exc_info=True)
        return None
