"""
Router de Shipping — Cotizaciones de envío via Envia.

Endpoints:
  POST /api/v1/shipping/quote    — cotizar envío via Envia   [owner, manager]
  GET  /api/v1/shipping/history  — historial de cotizaciones

Prerequisito: tenant debe tener Envia conectado (status=connected en tenant_integrations).
Referencia de diseño: docs/integrations/courier-envia.md
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from integrations.envia_client import EnviaClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Shipping"])


# ─── Modelos ─────────────────────────────────────────────────────────────────

class Address(BaseModel):
    name: str
    company: Optional[str] = None
    phone: str
    email: Optional[str] = None
    street: str
    number: str
    district: Optional[str] = None
    city: str
    state: str
    country: str = "MX"
    postalCode: str
    reference: Optional[str] = None


class Parcel(BaseModel):
    weight: float = Field(..., gt=0, description="Peso en kg")
    length: float = Field(..., gt=0, description="Largo en cm")
    width: float = Field(..., gt=0, description="Ancho en cm")
    height: float = Field(..., gt=0, description="Alto en cm")
    insuranceAmount: float = Field(default=0, ge=0)


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

    payload = {
        "origin": req.origin.model_dump(exclude_none=True),
        "destination": req.destination.model_dump(exclude_none=True),
        "parcels": [p.model_dump() for p in req.parcels],
        "shipment": {"carrier": "all", "type": 1},
    }

    try:
        quote_response = await client.get_rates(payload)
    except Exception as e:
        logger.error("Error obteniendo rates de Envia tenant %s: %s", tenant_id, e)
        raise HTTPException(
            status_code=502,
            detail="Error al contactar Envia. Verifica que la API key sea válida."
        )

    # Guardar cotización en shipments
    shipment_result = supabase.table("shipments").insert({
        "tenant_id": tenant_id,
        "order_id": req.order_id,
        "status": "quoted",
        "origin_address": req.origin.model_dump(exclude_none=True),
        "destination_address": req.destination.model_dump(exclude_none=True),
        "parcels": [p.model_dump() for p in req.parcels],
        "quote_response": quote_response,
    }).execute()

    shipment_id = shipment_result.data[0]["id"] if shipment_result.data else None

    return {
        "shipment_id": shipment_id,
        "rates": quote_response,
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
