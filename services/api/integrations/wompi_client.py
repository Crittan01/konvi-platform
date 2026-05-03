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

    # Wompi (CO docs sept-2024+) envía properties relativas a `data` —
    # ej. "transaction.id" se extrae de payload["data"]["transaction"]["id"],
    # NO de payload["transaction"]["id"]. Pero docs antiguos podían usar
    # paths absolutos. Intentamos ambos: primero data-relative, después
    # root. El que produzca valores no-vacíos es el correcto.
    def _traverse(root: object, dotted_path: str) -> str:
        cur: object = root
        for key in dotted_path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(key, "")
            else:
                return ""
        if cur is None:
            return ""
        return str(cur)

    data_root = payload.get("data") if isinstance(payload, dict) else None

    parts: list[str] = []
    for prop in properties:
        v_data = _traverse(data_root, prop) if isinstance(data_root, dict) else ""
        v_root = _traverse(payload, prop)
        # Preferir el path data-relative si aporta valor; root como fallback
        # (compat con eventos legacy o non-data-wrapped en pruebas).
        chosen = v_data if v_data else v_root
        parts.append(chosen)

    concat = "".join(parts) + str(timestamp) + events_key
    computed = hashlib.sha256(concat.encode()).hexdigest().upper()
    valid = computed == expected_checksum.upper()

    if not valid:
        # Diagnóstico: log de las properties usadas (sin secrets) para
        # facilitar debugging si falla en producción.
        _props_preview = ", ".join(
            f"{p}={v[:24]}…" if len(v) > 24 else f"{p}={v}"
            for p, v in zip(properties, parts)
        )
        logger.warning(
            "[WOMPI] Firma inválida. computed=%s received=%s ts=%s props=[%s]",
            computed[:12] + "...",
            expected_checksum[:12] + "...",
            timestamp,
            _props_preview,
        )
    return valid


# Tipos de documento aceptados en customer_data Wompi (CO). La doc pública
# lista CC/CE/NIT explícitamente para PSE; PP/TI/OTHER son aceptados en
# práctica por el endpoint payment_links. Mantenemos el set completo del
# repo (rev. 68) porque está validado en producción contra Wompi sandbox+prod
# desde 2026-04. Si Wompi cambia la política y devuelve 422 para alguno,
# se ajusta acá puntualmente — no pre-mapeamos silenciosamente.
_WOMPI_LEGAL_ID_TYPES_ACCEPTED = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}


def _build_customer_data(contact: Optional[dict]) -> Optional[dict]:
    """Construye el bloque customer_data Wompi a partir del contacto.

    Reglas (rev. 68, validadas en producción):
      - Solo se incluyen claves con valor (Wompi devuelve 422 ante nulls
        explícitos en strings).
      - ``legal_id_type`` se envía tal cual el cliente lo dió, dentro del
        set aceptado por el repo. Si el tipo no está en el set, no se
        envía documento (mejor que pre-mapear a otro tipo y mentirle al
        merchant en su backoffice).
      - ``phone_number_prefix`` separado (ej. ``+57``) según schema oficial.

    Ref: https://docs.wompi.co/docs/colombia/widget-checkout-web/
    """
    if not contact:
        return None
    cd: dict = {}

    # Email (lowercase normalizado upstream)
    email = (contact.get("email") or "").strip()
    if email:
        cd["email"] = email

    full_name = (contact.get("name") or "").strip()
    if full_name:
        cd["full_name"] = full_name

    # Teléfono Wompi: split prefix + number. WhatsApp guarda con + (ej. +573001234567).
    phone = (contact.get("phone") or "").strip()
    if phone:
        digits = phone.lstrip("+").lstrip("0")
        if digits.startswith("57") and len(digits) >= 12:
            cd["phone_number_prefix"] = "+57"
            cd["phone_number"] = digits[2:]
        else:
            # Fallback: solo number sin prefix. Wompi puede aceptarlo o ignorarlo
            # según el método. No agregar prefix=null porque Wompi rechaza nulls.
            cd["phone_number"] = digits

    # Documento: ambos juntos o ninguno (regla Wompi).
    doc_type_raw = (contact.get("document_type") or "").strip().upper()
    doc_num = (contact.get("document_number") or "").strip()
    if doc_type_raw and doc_num and doc_type_raw in _WOMPI_LEGAL_ID_TYPES_ACCEPTED:
        cd["legal_id"] = doc_num
        cd["legal_id_type"] = doc_type_raw

    return cd or None


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
    contact: Optional[dict] = None,
) -> dict:
    """
    Versión síncrona de create_payment_link — para BackgroundTasks y webhooks síncronos.
    Rev. 68 — recibe `contact` opcional para pre-poblar customer_data en checkout.
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
    customer_data = _build_customer_data(contact)
    if customer_data:
        payload["customer_data"] = customer_data
        logger.info(
            "[WOMPI] payment_link customer_data fields=%s",
            sorted(customer_data.keys()),
        )
    else:
        logger.warning(
            "[WOMPI] payment_link sin customer_data — checkout pedirá datos al cliente. order=%s",
            order_id,
        )

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
    contact: Optional[dict] = None,
) -> dict:
    """
    Crea un link de pago en Wompi.

    Campos requeridos por Wompi: name, description, single_use, collect_shipping.
    Correlación orden↔pago: order_id en campo `sku` (UUID v4 = 36 chars exactos).
    Rev. 68 — pre-popula `customer_data` desde el contacto para checkout sin re-tipear.

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
    customer_data = _build_customer_data(contact)
    if customer_data:
        payload["customer_data"] = customer_data
        logger.info(
            "[WOMPI] payment_link customer_data fields=%s order=%s",
            sorted(customer_data.keys()),
            order_id,
        )
    else:
        logger.warning(
            "[WOMPI] payment_link sin customer_data — checkout pedirá datos al cliente. order=%s",
            order_id,
        )

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
