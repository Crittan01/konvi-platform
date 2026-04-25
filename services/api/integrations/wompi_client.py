"""
Cliente HTTP para la API de Wompi Colombia.

Referencia oficial: https://docs.wompi.co/en/docs/colombia/
Validado: 2026-04-24

Ambientes:
  Sandbox:    https://sandbox.wompi.co/v1
  Producción: https://production.wompi.co/v1

Algoritmo de firma webhook: SHA256 simple sobre string concatenado
(no HMAC) — ver verify_event_signature().
"""
import hashlib
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WOMPI_SANDBOX_URL = "https://sandbox.wompi.co/v1"
WOMPI_PROD_URL = "https://production.wompi.co/v1"

WOMPI_ENV = os.getenv("WOMPI_ENV", "sandbox").strip().lower()
_is_prod = WOMPI_ENV == "production"

WOMPI_BASE_URL = WOMPI_PROD_URL if _is_prod else WOMPI_SANDBOX_URL
WOMPI_PRIVATE_KEY = os.getenv(
    "WOMPI_PRIVATE_KEY_PROD" if _is_prod else "WOMPI_PRIVATE_KEY_SANDBOX", ""
)
WOMPI_EVENTS_KEY = os.getenv(
    "WOMPI_EVENTS_KEY_PROD" if _is_prod else "WOMPI_EVENTS_KEY_SANDBOX", ""
)

REQUEST_TIMEOUT_SECONDS = 15


def verify_event_signature(payload: dict) -> bool:
    """
    Valida la firma de un evento webhook de Wompi.

    Algoritmo oficial (SHA256 simple, no HMAC):
      1. Concatenar valores de signature.properties en orden
      2. Concatenar timestamp (entero Unix)
      3. Concatenar events_key
      4. SHA256 del string completo
      5. Comparar con signature.checksum

    Referencia: https://docs.wompi.co/en/docs/colombia/eventos/
    """
    if not WOMPI_EVENTS_KEY:
        logger.error("[WOMPI] WOMPI_EVENTS_KEY no configurada — rechazando evento")
        return False

    sig = payload.get("signature", {})
    properties = sig.get("properties", [])
    expected_checksum = sig.get("checksum", "")
    timestamp = payload.get("timestamp", 0)

    if not expected_checksum or not properties:
        logger.warning("[WOMPI] Payload sin signature.properties o checksum")
        return False

    data = payload.get("data", {})
    parts = []
    for prop in properties:
        val = data
        for key in prop.split("."):
            val = val.get(key, "") if isinstance(val, dict) else ""
        parts.append(str(val))

    concat = "".join(parts) + str(timestamp) + WOMPI_EVENTS_KEY
    computed = hashlib.sha256(concat.encode()).hexdigest().upper()
    valid = computed == expected_checksum.upper()

    if not valid:
        logger.warning(
            "[WOMPI] Firma inválida. computed=%s received=%s",
            computed[:12] + "...",
            expected_checksum[:12] + "...",
        )
    return valid


def create_payment_link_sync(
    *,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
) -> dict:
    """
    Versión síncrona de create_payment_link — para BackgroundTasks y webhooks síncronos.
    Mismos parámetros y respuesta que create_payment_link.
    """
    if not WOMPI_PRIVATE_KEY:
        raise ValueError("WOMPI_PRIVATE_KEY no configurada")

    payload = {
        "name": name[:100],
        "description": description[:255],
        "single_use": True,
        "collect_shipping": False,
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "expires_at": expires_at,
        "sku": order_id,
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{WOMPI_BASE_URL}/payment_links",
            headers={"Authorization": f"Bearer {WOMPI_PRIVATE_KEY}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

    link_id = data.get("id", "")
    return {
        "link_id": link_id,
        "checkout_url": f"https://checkout.wompi.co/l/{link_id}",
        "active": data.get("active", False),
        "amount_in_cents": data.get("amount_in_cents"),
        "expires_at": data.get("expires_at"),
    }


async def create_payment_link(
    *,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
) -> dict:
    """
    Crea un link de pago en Wompi.

    Campos requeridos por Wompi: name, description, single_use, collect_shipping.
    Correlación orden↔pago: order_id en campo `sku` (UUID v4 = 36 chars exactos).

    Returns dict con:
      - link_id: str (id del payment link)
      - checkout_url: str (https://checkout.wompi.co/l/{id})
      - active: bool
    Raises httpx.HTTPStatusError on HTTP errors.
    """
    if not WOMPI_PRIVATE_KEY:
        raise ValueError("WOMPI_PRIVATE_KEY no configurada")

    payload = {
        "name": name[:100],
        "description": description[:255],
        "single_use": True,
        "collect_shipping": False,
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "expires_at": expires_at,
        "sku": order_id,  # UUID v4 = 36 chars, cabe exacto en el campo
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{WOMPI_BASE_URL}/payment_links",
            headers={"Authorization": f"Bearer {WOMPI_PRIVATE_KEY}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

    link_id = data.get("id", "")
    return {
        "link_id": link_id,
        "checkout_url": f"https://checkout.wompi.co/l/{link_id}",
        "active": data.get("active", False),
        "amount_in_cents": data.get("amount_in_cents"),
        "expires_at": data.get("expires_at"),
    }
