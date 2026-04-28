"""
Cliente HTTP para la API de Wompi Colombia.

Referencia oficial: https://docs.wompi.co/en/docs/colombia/
Validado: 2026-04-24

Ambientes:
  Sandbox:    https://sandbox.wompi.co/v1
  Producción: https://production.wompi.co/v1

Algoritmo de firma webhook: SHA256 simple sobre string concatenado
(no HMAC) — ver verify_event_signature().

Credenciales: por-tenant en tenant_integrations (provider='wompi'),
almacenadas en Supabase Vault. No se usan env vars globales.
"""
import hashlib
import logging
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

WOMPI_SANDBOX_URL = "https://sandbox.wompi.co/v1"
WOMPI_PROD_URL = "https://production.wompi.co/v1"

REQUEST_TIMEOUT_SECONDS = 15


def wompi_base_url(environment: str) -> str:
    return WOMPI_PROD_URL if environment == "production" else WOMPI_SANDBOX_URL


def get_tenant_wompi_creds(supabase, tenant_id: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Lee private_key, events_key y environment desde tenant_integrations (Vault).
    Retorna (private_key, events_key, environment).
    Retorna (None, None, "sandbox") si el tenant no tiene Wompi configurado.
    """
    try:
        from vault_helper import VaultHelper, resolve_secret
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "wompi")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
        if not res.data:
            return None, None, "sandbox"

        creds = res.data.get("credentials", {})
        meta = res.data.get("meta", {})
        environment = meta.get("environment", "sandbox")

        vault = VaultHelper(supabase)
        private_key = resolve_secret(vault, creds, "private_key")
        events_key = resolve_secret(vault, creds, "events_key")

        return private_key, events_key, environment
    except Exception as e:
        logger.error("[WOMPI] error_leyendo_creds tenant=%s error=%s", tenant_id, e)
        return None, None, "sandbox"


def verify_event_signature(payload: dict, events_key: str) -> bool:
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
    if not events_key:
        logger.error("[WOMPI] events_key no configurada — rechazando evento")
        return False

    sig = payload.get("signature", {})
    properties = sig.get("properties", [])
    expected_checksum = sig.get("checksum", "")
    timestamp = payload.get("timestamp", 0)

    if not expected_checksum or not properties:
        logger.warning("[WOMPI] Payload sin signature.properties o checksum")
        return False

    parts = []
    for prop in properties:
        val: object = payload  # traversal desde ROOT — "data.transaction.id" → payload["data"]["transaction"]["id"]
        for key in prop.split("."):
            val = val.get(key, "") if isinstance(val, dict) else ""
        parts.append(str(val))

    concat = "".join(parts) + str(timestamp) + events_key
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
    private_key: str,
    environment: str,
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
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")

    base_url = wompi_base_url(environment)
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
            f"{base_url}/payment_links",
            headers={"Authorization": f"Bearer {private_key}"},
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
    private_key: str,
    environment: str,
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
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")

    base_url = wompi_base_url(environment)
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
            f"{base_url}/payment_links",
            headers={"Authorization": f"Bearer {private_key}"},
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
