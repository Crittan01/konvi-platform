"""
Router de Shipping — Cotizaciones de envío via Envia.

Endpoints:
  POST /api/v1/shipping/quote    — cotizar envío via Envia   [owner, manager]
  GET  /api/v1/shipping/history  — historial de cotizaciones

Prerequisito: tenant debe tener Envia conectado (status=connected en tenant_integrations).
Referencia de diseño: docs/integrations/courier-envia.md
"""
import asyncio
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from integrations.envia_client import EnviaClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Shipping"])


# ─── Mapeo departamentos Colombia → ISO 3166-2:CO ────────────────────────────
# Envia valida state con códigos ISO. Confirmado: Bogotá = "DC" (no "BOG").
# La UI envía el nombre completo del departamento; aquí se normaliza.
_CO_STATE_CODES: dict[str, str] = {
    "Amazonas": "AMA", "Antioquia": "ANT", "Arauca": "ARA",
    "Atlántico": "ATL",
    "Bogotá D.C.": "DC", "Bogota D.C.": "DC",
    "Bolívar": "BOL", "Boyacá": "BOY", "Caldas": "CAL",
    "Caquetá": "CAQ", "Casanare": "CAS", "Cauca": "CAU",
    "Cesar": "CES", "Chocó": "CHO", "Córdoba": "COR",
    "Cundinamarca": "CUN", "Guainía": "GUA", "Guaviare": "GUV",
    "Huila": "HUI", "La Guajira": "LAG", "Magdalena": "MAG",
    "Meta": "MET", "Nariño": "NAR", "Norte de Santander": "NSA",
    "Putumayo": "PUT", "Quindío": "QUI", "Risaralda": "RIS",
    "San Andrés y Providencia": "SAP", "Santander": "SAN",
    "Sucre": "SUC", "Tolima": "TOL", "Valle del Cauca": "VAC",
    "Vaupés": "VAU", "Vichada": "VID",
}


def _normalize_state(state: str, country: str) -> str:
    """Convierte nombre largo de departamento al código corto que Envia acepta."""
    if country != "CO" or len(state) <= 3:
        return state
    return _CO_STATE_CODES.get(state, state[:3].upper())


# ─── Modelos ─────────────────────────────────────────────────────────────────

class Address(BaseModel):
    name: str
    company: Optional[str] = None
    phone: str
    email: Optional[str] = None
    street: str
    number: Optional[str] = None
    district: Optional[str] = None
    city: str
    state: str
    country: str = "CO"
    postalCode: str
    reference: Optional[str] = None
    # Para Colombia: código DANE 8 dígitos (ej. "11001000") — no se envía a Envia, se usa internamente
    dane_code: Optional[str] = None


class Parcel(BaseModel):
    weight: float = Field(..., gt=0, description="Peso en kg")
    length: float = Field(..., gt=0, description="Largo en cm")
    width: float = Field(..., gt=0, description="Ancho en cm")
    height: float = Field(..., gt=0, description="Alto en cm")
    insuranceAmount: float = Field(default=0, ge=0)
    content: str = Field(default="Mercancía general")
    amount: int = Field(default=1, ge=1)


class QuoteRequest(BaseModel):
    order_id: Optional[str] = None
    origin: Address
    destination: Address
    parcels: List[Parcel] = Field(..., min_length=1)


# ─── Helper ──────────────────────────────────────────────────────────────────

def _get_envia_client(tenant_id: str, supabase: Client) -> EnviaClient:
    """
    Obtiene las credenciales de Envia del tenant desde tenant_integrations.
    Lanza 400 si no está conectado.
    """
    result = (
        supabase.table("tenant_integrations")
        .select("credentials, status")
        .eq("tenant_id", tenant_id)
        .eq("provider", "envia")
        .single()
        .execute()
    )
    if not result.data or result.data.get("status") != "connected":
        raise HTTPException(
            status_code=400,
            detail="Envia no está conectado. Ve a /dashboard/integrations para configurarlo."
        )
    creds = result.data.get("credentials", {})
    api_token = creds.get("api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="API token de Envia no encontrado")

    sandbox = creds.get("sandbox", False)
    return EnviaClient(api_token=api_token, sandbox=sandbox)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/quote", response_model=dict, status_code=201)
async def quote_shipment(
    req: QuoteRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Cotiza un envío via Envia y guarda el resultado en shipments.
    Retorna las opciones de carrier/tarifa disponibles.
    """
    client = _get_envia_client(tenant_id, supabase)

    # Construir packages con estructura real de Envia (validada sandbox 2026-04-17):
    # dimensiones anidadas, campos content/amount/type requeridos, carrier != "all" en CO.
    packages = [
        {
            "weight":         p.weight,
            "dimensions":     {"length": p.length, "width": p.width, "height": p.height},
            "content":        p.content,
            "amount":         p.amount,
            "type":           "box",
            "declaredValue":  0,
            "lengthUnit":     "CM",
            "weightUnit":     "KG",
        }
        for p in req.parcels
    ]

    def _addr(a: Address) -> dict:
        d = a.model_dump(exclude_none=True)
        d.pop("dane_code", None)  # campo interno — no va a Envia
        d["state"] = _normalize_state(a.state, a.country)
        if a.country == "CO" and a.dane_code:
            # Para Colombia: city y postalCode deben ser el código DANE 8 dígitos
            d["city_to_display"] = a.city
            d["city"]            = a.dane_code
            d["postalCode"]      = a.dane_code
        return d

    base_payload = {
        "origin":      _addr(req.origin),
        "destination": _addr(req.destination),
        "packages":    packages,
        "settings":    {"currency": "COP"},
    }

    # Carriers activos en la cuenta (confirmado en panel Envia 2026-04-17).
    # Nombres exactos según GET /available-carrier/CO/0.
    _CO_CARRIERS = [
        "tcc", "serviEntrega", "coordinadora", "interRapidisimo",
        "deprisa", "mensajerosUrbanos", "noventa9Minutos",
        "fedex", "dhl", "envia",
    ]

    async def _fetch_carrier(carrier: str):
        payload = {**base_payload, "shipment": {"carrier": carrier, "type": 1}}
        try:
            resp = await client.get_rates(payload)
            return resp.get("data") if isinstance(resp, dict) else resp
        except Exception as exc:
            logger.warning("Envia carrier %s falló (tenant %s): %s", carrier, tenant_id, exc)
            return []

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_fetch_carrier(c) for c in _CO_CARRIERS]),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        logger.error("Timeout global cotizando carriers Envia para tenant %s", tenant_id)
        raise HTTPException(status_code=502, detail="Timeout al consultar carriers de Envia.")

    raw_rates: list = []
    for chunk in results:
        if isinstance(chunk, list):
            raw_rates.extend(chunk)

    if not raw_rates:
        raise HTTPException(
            status_code=502,
            detail="Envia no retornó tarifas. Verifica la API key y que el account tenga carriers activos para Colombia."
        )

    normalized_rates = []
    for r in raw_rates:
        dd = r.get("deliveryDate")
        normalized_rates.append({
            "carrier":            r.get("carrierDescription") or r.get("carrier", ""),
            "service":            r.get("serviceDescription") or r.get("service", ""),
            "total_price":        r.get("totalPrice"),
            "currency":           r.get("currency", "COP"),
            "delivery_date":      dd.get("date") if isinstance(dd, dict) else dd,
            "delivery_estimate":  r.get("deliveryEstimate"),
            # Campos para label en Fase 2
            "carrierId":          r.get("carrierId"),
            "serviceId":          r.get("serviceId"),
            "carrier_code":       r.get("carrier"),
            "service_code":       r.get("service"),
        })

    # Guardar cotización en shipments
    shipment_result = supabase.table("shipments").insert({
        "tenant_id":           tenant_id,
        "order_id":            req.order_id,
        "status":              "quoted",
        "origin_address":      req.origin.model_dump(exclude_none=True),
        "destination_address": req.destination.model_dump(exclude_none=True),
        "parcels":             [p.model_dump() for p in req.parcels],
        "quote_response":      {"data": raw_rates},
    }).execute()

    shipment_id = shipment_result.data[0]["id"] if shipment_result.data else None

    return {
        "shipment_id": shipment_id,
        "rates":       normalized_rates,
    }


@router.get("/history", response_model=List[dict])
async def get_shipping_history(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna historial de cotizaciones y envíos del tenant."""
    try:
        result = (
            supabase.table("shipments")
            .select("id, status, carrier, service, tracking_number, estimated_delivery, created_at, order_id")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error("Error obteniendo historial shipping tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener historial")
