import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt
from supabase import Client

logger = logging.getLogger("orchestrator.tools.shipping_quote")

API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

DEFAULT_WEIGHT_KG = float(os.getenv("INBOX_SHIPPING_DEFAULT_WEIGHT_KG", "1"))
DEFAULT_LENGTH_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_LENGTH_CM", "10"))
DEFAULT_WIDTH_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_WIDTH_CM", "10"))
DEFAULT_HEIGHT_CM = float(os.getenv("INBOX_SHIPPING_DEFAULT_HEIGHT_CM", "10"))
SHIPPING_REQUEST_TIMEOUT_SECONDS = float(os.getenv("INBOX_SHIPPING_TIMEOUT_SECONDS", "25"))

_SHIPPING_KEYWORDS = {
    "envio",
    "enviar",
    "domicilio",
    "flete",
    "entrega",
    "costo envio",
    "valor envio",
    "cuanto cuesta enviar",
    "cotizar envio",
    "cotizacion envio",
}


@dataclass
class ShippingQuoteResult:
    handled: bool
    response_text: Optional[str] = None
    requires_human: bool = False


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def is_shipping_quote_query(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    for token in _SHIPPING_KEYWORDS:
        if token in normalized:
            return True
    return False


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _extract_weight_kg(text: str) -> Optional[float]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    kg_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|kilo|kilos)", normalized)
    if kg_match:
        value = _safe_float(kg_match.group(1))
        if value and value > 0:
            return value

    g_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(g|gr|gramo|gramos)", normalized)
    if g_match:
        value = _safe_float(g_match.group(1))
        if value and value > 0:
            return max(value / 1000.0, 0.05)

    return None


def _sanitize_dane_code(raw: object) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 8 and digits.endswith("000"):
        return digits[:5]
    if len(digits) == 5:
        return digits
    return ""


def _format_money(value: object, currency: str = "COP") -> str:
    amount = _safe_float(value)
    if amount is None:
        return "N/D"
    if currency.upper() == "COP":
        return f"${int(round(amount)):,.0f}".replace(",", ".")
    return f"{amount:.2f} {currency.upper()}"


def _format_eta(rate: dict) -> str:
    delivery_date = str(rate.get("delivery_date") or "").strip()
    if delivery_date:
        try:
            dt = datetime.fromisoformat(delivery_date.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            return delivery_date

    estimate = str(rate.get("delivery_estimate") or "").strip()
    if estimate:
        return estimate
    return "N/D"


def _format_rate_line(label: str, rate: dict) -> str:
    carrier = str(rate.get("carrier") or "carrier").strip()
    service = str(rate.get("service") or "servicio").strip()
    currency = str(rate.get("currency") or "COP")
    total = _format_money(rate.get("total_price"), currency)
    eta = _format_eta(rate)
    return f"{label}: {carrier} {service}, {total}, entrega {eta}."


def _build_quote_response_text(origin: dict, highlights: dict) -> Optional[str]:
    cheapest = highlights.get("cheapest") if isinstance(highlights, dict) else None
    fastest = highlights.get("fastest") if isinstance(highlights, dict) else None
    if not isinstance(cheapest, dict):
        return None

    origin_city = str(origin.get("city") or "origen configurado")
    line_one = f"Desde {origin_city} te cotizo:"
    cheapest_line = _format_rate_line("Mas economica", cheapest)

    if isinstance(fastest, dict):
        same = (
            str(fastest.get("carrier") or "") == str(cheapest.get("carrier") or "")
            and str(fastest.get("service") or "") == str(cheapest.get("service") or "")
            and str(fastest.get("total_price") or "") == str(cheapest.get("total_price") or "")
        )
        if same:
            return f"{line_one} {cheapest_line} Tambien es la mas rapida."
        fastest_line = _format_rate_line("Mas rapida", fastest)
        return f"{line_one} {cheapest_line} {fastest_line}"

    return f"{line_one} {cheapest_line}"


def _build_api_auth_token(tenant_id: str) -> Optional[str]:
    if not SUPABASE_JWT_SECRET:
        return None
    now = datetime.now(timezone.utc)
    payload = {
        "aud": "authenticated",
        "sub": "00000000-0000-0000-0000-000000000000",
        "role": "authenticated",
        "email": "orchestrator@system.local",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "app_metadata": {
            "tenant_id": tenant_id,
            "role": "owner",
        },
        "user_metadata": {},
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def _query_bogota_origin_hint(query_text: str) -> Optional[dict]:
    normalized = _normalize_text(query_text)
    if "bogota" not in normalized:
        return None
    return {
        "city": "Bogota D.C.",
        "state": "Bogota D.C.",
        "country": "CO",
        "dane_code": "11001",
        "postal_code": "11001",
    }


def _coerce_origin(raw: Optional[dict], query_text: str) -> Optional[dict]:
    source = dict(raw or {})
    if not source:
        hinted = _query_bogota_origin_hint(query_text)
        if hinted:
            source = hinted

    if not source:
        return None

    city = str(source.get("city") or "").strip()
    state = str(source.get("state") or "").strip()
    country = str(source.get("country") or "CO").strip().upper() or "CO"
    dane_code = _sanitize_dane_code(source.get("dane_code") or source.get("postal_code"))
    if not dane_code:
        return None

    return {
        "city": city or "Bogota D.C.",
        "state": state or "Bogota D.C.",
        "country": country,
        "postalCode": dane_code,
        "dane_code": dane_code,
    }


def _coerce_destination(raw: Optional[dict]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    city = str(raw.get("city") or "").strip()
    state = str(raw.get("state") or "").strip()
    country = str(raw.get("country") or "CO").strip().upper() or "CO"
    dane_code = _sanitize_dane_code(raw.get("dane_code") or raw.get("postal_code"))
    if not dane_code:
        return None

    return {
        "city": city,
        "state": state,
        "country": country,
        "postalCode": dane_code,
        "dane_code": dane_code,
    }


def _build_quote_payload(origin: dict, destination: dict, weight_kg: float) -> dict:
    safe_weight = max(weight_kg, 0.05)
    return {
        "origin": origin,
        "destination": destination,
        "parcels": [
            {
                "weight": safe_weight,
                "length": DEFAULT_LENGTH_CM,
                "width": DEFAULT_WIDTH_CM,
                "height": DEFAULT_HEIGHT_CM,
                "insuranceAmount": 0,
            }
        ],
    }


def _get_tenant_shipping_origin(supabase: Client, tenant_id: str) -> Optional[dict]:
    res = (
        supabase.table("tenants")
        .select("shipping_origin")
        .eq("id", tenant_id)
        .single()
        .execute()
    )
    return (res.data or {}).get("shipping_origin")


def _get_conversation_customer_phone(supabase: Client, conversation_id: str) -> Optional[str]:
    res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not res.data:
        return None
    return str(res.data.get("customer_phone") or "").strip() or None


def _get_contact_address(
    supabase: Client,
    tenant_id: str,
    customer_phone: Optional[str],
) -> Optional[dict]:
    if not customer_phone:
        return None

    res = (
        supabase.table("contacts")
        .select("address")
        .eq("tenant_id", tenant_id)
        .eq("phone", customer_phone)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    address = rows[0].get("address")
    return address if isinstance(address, dict) else None


async def _request_shipping_quote(tenant_id: str, payload: dict) -> tuple[int, dict]:
    token = _build_api_auth_token(tenant_id)
    if not token:
        return 500, {"detail": "SUPABASE_JWT_SECRET no configurado en orquestador."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"inbox-quote-{uuid.uuid4()}",
    }

    timeout = httpx.Timeout(SHIPPING_REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{API_URL}/api/v1/shipping/quote", json=payload, headers=headers)
        body = resp.json() if resp.content else {}
        if not isinstance(body, dict):
            body = {"detail": "Respuesta inválida del servicio de shipping."}
        return resp.status_code, body


async def handle_shipping_quote_if_applicable(
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
    query_text: str,
) -> ShippingQuoteResult:
    if not is_shipping_quote_query(query_text):
        return ShippingQuoteResult(handled=False)

    try:
        origin_cfg = _get_tenant_shipping_origin(supabase, tenant_id)
        origin = _coerce_origin(origin_cfg, query_text)
        if not origin:
            return ShippingQuoteResult(
                handled=True,
                response_text=(
                    "Para cotizar envio necesito el origen configurado del negocio. "
                    "Por favor configura origen en Ajustes > Direccion de envio."
                ),
                requires_human=True,
            )

        phone = _get_conversation_customer_phone(supabase, conversation_id)
        contact_address = _get_contact_address(supabase, tenant_id, phone)
        destination = _coerce_destination(contact_address)
        if not destination:
            return ShippingQuoteResult(
                handled=True,
                response_text=(
                    "Para cotizar envio necesito tu ciudad de entrega. "
                    "Comparteme departamento y ciudad para calcularla."
                ),
            )

        weight = _extract_weight_kg(query_text) or DEFAULT_WEIGHT_KG
        payload = _build_quote_payload(origin, destination, weight)
        status_code, body = await _request_shipping_quote(tenant_id, payload)

        if status_code >= 400:
            detail = str(body.get("detail") or "No pude cotizar el envio en este momento.")
            requires_human = status_code >= 500
            return ShippingQuoteResult(
                handled=True,
                response_text=f"No pude cotizar el envio: {detail}",
                requires_human=requires_human,
            )

        highlights = body.get("highlights") if isinstance(body, dict) else {}
        message = _build_quote_response_text(origin, highlights)
        if not message:
            return ShippingQuoteResult(
                handled=True,
                response_text="No llegaron tarifas disponibles en este momento. Intentemos nuevamente en unos minutos.",
                requires_human=True,
            )
        return ShippingQuoteResult(handled=True, response_text=message)
    except Exception as exc:
        logger.error("Error en shipping_quote_tool tenant=%s: %s", tenant_id, exc, exc_info=True)
        return ShippingQuoteResult(
            handled=True,
            response_text="No pude cotizar el envio ahora mismo. Te apoyo con un asesor humano.",
            requires_human=True,
        )
