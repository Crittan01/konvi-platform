"""
Router de Shipping — Cotizaciones de envío via provider activo (Aveonline).

Endpoints (post-eliminación Envia rev. 109):
  POST /api/v1/shipping/quote          — cotizar envío via Aveonline       [owner, manager]
  PATCH /api/v1/shipping/{id}/rate     — confirmar tarifa seleccionada     [owner, manager]
  DELETE /api/v1/shipping/orphans      — purgar cotizaciones huérfanas     [owner, manager]
  GET  /api/v1/shipping/history        — historial de cotizaciones

Prerequisito: tenant debe tener Aveonline conectado (provider único activo,
ver ADR-0019). Para futuros couriers seguir ADR-0023 (Shipping Provider
Integration Pattern).

Nota histórica: endpoints label/tracking/pickup/cancel eliminados con Envia.
Aveonline maneja eventos de estado vía webhook (routers/aveonline_webhook.py)
y guía se genera implícitamente al confirmar orden.
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from dependencies.idempotency import (
    abort_idempotency,
    begin_idempotency,
    finalize_idempotency,
    payload_fingerprint,
)
from dependencies.internal_auth import (
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
    require_write_internal_or_user,
)
from dependencies.plans import PLAN_SHIPPING_CONFIRM_RATE, PLAN_SHIPPING_QUOTE
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Shipping"])


# ─── Mapeo departamentos Colombia → ISO 3166-2:CO ────────────────────────────
# La UI envía el nombre completo del departamento; aquí se normaliza al
# código corto ISO usado por providers shipping.
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


def _normalize_country(country: Optional[str], default: str = "CO") -> str:
    """
    Normaliza país a formato operativo del provider shipping activo.
    Acepta alias comunes de Colombia y retorna "CO".
    """
    raw = str(country or "").strip()
    if not raw:
        return default

    ascii_country = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    token = re.sub(r"[^A-Za-z]", "", ascii_country).upper()
    if not token:
        return default

    if token in {"CO", "COL", "COLOMBIA"}:
        return "CO"
    if len(token) == 2:
        return token
    return token


def _normalize_state(state: str, country: str) -> str:
    """Convierte nombre largo de departamento al código corto ISO 3166-2:CO."""
    country_code = _normalize_country(country, default="CO")
    if country_code != "CO" or len(state) <= 3:
        return state
    return _CO_STATE_CODES.get(state, state[:3].upper())


# Rev. 72 — sanitización DANE centralizada en `dependencies/dane.py`.
# Aliases locales para no romper call-sites históricos en este módulo.
from dependencies.dane import sanitize_dane_code as _sanitize_dane_code  # noqa: E402,F401

# Nota rev. 109: helpers Envia (_validate_co_address_with_envia,
# _resolve_carriers_for_quote, _extract_carrier_name) eliminados con el
# pivote a Aveonline (ADR-0019). Aveonline tiene su propio path en
# `_quote_via_aveonline` que NO necesita estos helpers — usa
# `to_aveonline_city_format` internamente y resuelve carriers via su API.


# ─── Modelos ─────────────────────────────────────────────────────────────────

class Address(BaseModel):
    # Campos requeridos solo para label — para cotización se usan valores por defecto
    name:       str            = Field(default="Remitente", min_length=2, max_length=120)
    company:    Optional[str]  = None
    phone:      str            = Field(default="3000000000", min_length=7, max_length=20)
    email:      Optional[str]  = None
    street:     str            = Field(default="Dirección por confirmar", min_length=3, max_length=180)
    number:     Optional[str]  = None
    district:   Optional[str]  = None
    city:       str            = Field(default="", max_length=120)
    state:      str            = Field(default="", max_length=120)
    country:    str            = "CO"
    postalCode: str            = Field(default="", max_length=20)
    reference:  Optional[str]  = None
    dane_code:  Optional[str]  = None


class Parcel(BaseModel):
    weight: float = Field(..., gt=0, description="Peso en kg")
    length: float = Field(..., gt=0, description="Largo en cm")
    width: float = Field(..., gt=0, description="Ancho en cm")
    height: float = Field(..., gt=0, description="Alto en cm")
    insuranceAmount: float = Field(default=0, ge=0)
    content: str = Field(default="Mercancía general", max_length=180)
    amount: int = Field(default=1, ge=1)
    # Sem 5 H.2.5 v2 — declaredValue per parcel.
    # Aveonline lo usa como base para cálculo de valuation. Carriers que
    # exponen seguro propio lo aplican internamente sobre este valor.
    declaredValueCop: Optional[int] = Field(
        default=None,
        ge=0,
        description="Valor declarado en pesos COP (NO cents). Si NULL o 0, "
                    "no se reparte declaredValue al payload.",
    )


class QuoteRequest(BaseModel):
    order_id: Optional[str] = None
    origin: Address
    destination: Address
    parcels: List[Parcel] = Field(..., min_length=1)


# ─── Helper ──────────────────────────────────────────────────────────────────

def _get_active_shipping_provider(tenant_id: str, supabase: Client) -> str:
    """Resuelve `active_provider` del tenant. Default 'aveonline' (provider
    activo único post-pivote rev. 107 — ver ADR-0019).

    Rev. 109 (2026-05-30): Envia eliminado del runtime. Tag archivo
    `archive/envia-investigacion-rev106-2026-05-08` preserva investigación
    histórica para rollback path teórico.
    """
    try:
        cfg = (
            supabase.table("tenant_shipping_provider_config")
            .select("active_provider")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if cfg and cfg.data:
            return (cfg.data.get("active_provider") or "aveonline").strip().lower()
    except Exception as exc:
        logger.warning(
            "No pude leer active_provider tenant=%s — default aveonline: %s",
            tenant_id, exc,
        )
    return "aveonline"


# ─── Aveonline routing helper (provider único activo post-rev. 107) ──────


async def _quote_via_aveonline(
    tenant_id: str,
    supabase: Client,
    req: "QuoteRequest",
) -> dict:
    """Branch del endpoint /quote para tenants con active_provider='aveonline'.

    Retorna el MISMO response shape que el flow Envia (rates + highlights +
    shipment_id) para preservar compat con el frontend Cotizador del Console.
    """
    from integrations.aveonline_client import (
        AveonlineAuthError,
        AveonlineClient,
        AveonlineNoCarriersError,
        AveonlinePackageLimitError,
        AveonlinePermanentError,
        AveonlineTransientError,
        to_aveonline_city_format,
    )

    # Convertir direcciones a formato Aveonline (uppercase city+state).
    origin_canonical = to_aveonline_city_format(
        req.origin.city or "", req.origin.state or "",
    )
    dest_canonical = to_aveonline_city_format(
        req.destination.city or "", req.destination.state or "",
    )
    if not origin_canonical or not dest_canonical:
        raise HTTPException(
            status_code=400,
            detail=(
                "No pude convertir origin/destination al formato Aveonline. "
                "Faltan city o state. Usa formato: city='Bogotá', state='Cundinamarca'."
            ),
        )

    # Agregar peso/dim de todos los parcels (Aveonline cotiza por paquete único).
    total_weight = sum(float(p.weight or 0) for p in req.parcels)
    max_length = max((float(p.length or 0) for p in req.parcels), default=10)
    max_width = max((float(p.width or 0) for p in req.parcels), default=10)
    total_height = sum(float(p.height or 0) for p in req.parcels)
    total_units = sum(int(p.amount or 1) for p in req.parcels) or 1
    declared_total = sum(int(p.declaredValueCop or 0) for p in req.parcels) or 50000
    first_content = (req.parcels[0].content if req.parcels else "Producto") or "Producto"

    client = AveonlineClient(tenant_id, supabase)
    try:
        result = await client.quote(
            origin={"city_canonical": origin_canonical, "city": req.origin.city},
            destination={"city_canonical": dest_canonical, "city": req.destination.city},
            package={
                "weight_kg": total_weight or 1.0,
                "length_cm": max_length,
                "width_cm": max_width,
                "height_cm": total_height or 10,
                "declared_value_cop": declared_total,
                "units": total_units,
                "product_name": first_content,
                "cod_enabled": False,
            },
        )
    except AveonlineAuthError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Aveonline no autenticado: {exc}. Reconecta en /dashboard/integrations/aveonline.",
        )
    except AveonlineNoCarriersError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Sin carriers Aveonline para {req.destination.city}: {exc}",
        )
    except AveonlinePackageLimitError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Paquete excede límites Aveonline: {exc}",
        )
    except AveonlineTransientError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Aveonline temporalmente no disponible: {exc}",
        )
    except AveonlinePermanentError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Aveonline error: {exc}",
        )

    # Mapear QuoteOption → shape `normalized_rates` Envia-compat + campos
    # extra Aveonline (rev. 107: logo, breakdown, COD, peso volumétrico).
    # El frontend lee: rate.carrier, rate.service, rate.total_price,
    # rate.currency, rate.delivery_estimate, rate.rate_id, rate.id + nuevos.
    rates = []
    for opt in result.options:
        rates.append({
            # Campos canónicos (compat Envia legacy frontend).
            "rate_id": opt.rate_id,
            "id": opt.rate_id,
            "carrier": opt.carrier_name,
            "service": opt.service_level,
            "total_price": opt.price_cents / 100,
            "currency": "COP",
            "delivery_estimate": (
                f"{opt.eta_days} días" if opt.eta_days else "consultar"
            ),
            "delivery_days": opt.eta_days,
            "provider": "aveonline",
            # Campos extendidos Aveonline (rev. 107) — el frontend puede
            # mostrarlos si los reconoce; si no, se ignoran sin romper compat.
            "carrier_logo_url": opt.logo_url,
            "carrier_logo_url_alt": opt.logo_url_alt,
            "route_code": opt.route_code,
            "route_type": opt.route_type,
            "weight_real_kg": opt.weight_real_kg,
            "weight_volumetric_kg": opt.weight_volumetric_kg,
            "units": opt.units,
            "declared_value_cop": opt.declared_value_cop,
            "valuation_percent": opt.valuation_percent,
            "freight_total_cop": (
                opt.freight_total_cents / 100 if opt.freight_total_cents else None
            ),
            "handling_cop": (
                opt.handling_cents / 100 if opt.handling_cents else None
            ),
            "cod_extras_cop": (
                opt.cod_extras_cents / 100 if opt.cod_extras_cents else None
            ),
            "subtotal_cop": (
                opt.subtotal_cents / 100 if opt.subtotal_cents else None
            ),
            "cod_supported": opt.cod_supported,
        })

    # Persistir shipment row para que /history funcione.
    # A3 finiquito (audit §3 BUG#1 CRITICAL): antes insertaba columnas `provider`
    # y `rates_snapshot` que NO existen en el schema real de `shipments` (verificado
    # en DB remota 2026-06-24) → el insert fallaba 100% (try/except silenciaba el
    # 400 'column does not exist') y el historial del Cotizador quedaba VACÍO tras
    # el pivote Envia→Aveonline. Fix: `provider` se elimina (no hay columna; el
    # provider es implícito Aveonline post-ADR-0019) y los rates van a la columna
    # canónica `quote_response`.
    shipment_id = None
    try:
        shipment_result = supabase.table("shipments").insert({
            "tenant_id": tenant_id,
            "status": "quoted",
            "origin_address": req.origin.model_dump(exclude_none=True),
            "destination_address": req.destination.model_dump(exclude_none=True),
            "parcels": [p.model_dump() for p in req.parcels],
            "quote_response": rates,
        }).execute()
        if shipment_result.data:
            shipment_id = shipment_result.data[0]["id"]
    except Exception as exc:
        logger.warning(
            "[shipping.quote.aveonline] persist shipment falló: %s", exc,
        )

    return {
        "shipment_id": shipment_id,
        "rates": rates,
        "highlights": _build_rate_highlights(rates),
        "provider": "aveonline",
    }


# Nota rev. 109: helpers Envia _require_envia_phase2/capability +
# _parse_envia_label_data + _parse_envia_track_data eliminados con el
# pivote a Aveonline (ADR-0019). Aveonline maneja eventos de estado vía
# webhook (routers/aveonline_webhook.py), no por polling/parsing manual.


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


def _parse_delivery_estimate_hours(raw: object) -> Optional[float]:
    if isinstance(raw, (int, float)):
        if raw > 0:
            return float(raw)
        return None

    if not isinstance(raw, str):
        return None

    text = raw.strip().lower()
    if not text:
        return None

    direct = _safe_float(text)
    if direct is not None and direct > 0:
        return direct

    # Parseo explícito de unidades para evitar inferencias ambiguas.
    hour_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(hora|horas|hr|hrs)", text)
    if hour_match:
        value = _safe_float(hour_match.group(1))
        if value is not None and value > 0:
            return value

    day_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(dia|dias|día|días)", text)
    if day_match:
        value = _safe_float(day_match.group(1))
        if value is not None and value > 0:
            return value * 24.0

    return None


def _parse_delivery_date_score(raw: object) -> Optional[float]:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _rate_speed_key(rate: dict) -> tuple[int, float]:
    delivery_date_score = _parse_delivery_date_score(rate.get("delivery_date"))
    if delivery_date_score is not None:
        return (0, delivery_date_score)

    estimate_hours = _parse_delivery_estimate_hours(rate.get("delivery_estimate"))
    if estimate_hours is not None:
        return (1, estimate_hours)

    return (2, float("inf"))


def _build_rate_highlights(rates: list[dict]) -> dict:
    valid_rates = [r for r in rates if isinstance(r, dict)]
    if not valid_rates:
        return {}

    priced_rates = [r for r in valid_rates if _safe_float(r.get("total_price")) is not None]
    cheapest = None
    if priced_rates:
        cheapest = min(priced_rates, key=lambda r: _safe_float(r.get("total_price")) or float("inf"))

    fastest = min(valid_rates, key=_rate_speed_key)
    if _rate_speed_key(fastest)[0] == 2:
        fastest = None

    highlights: dict[str, dict] = {}
    if cheapest is not None:
        highlights["cheapest"] = cheapest
    if fastest is not None:
        highlights["fastest"] = fastest
    return highlights


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/quote", response_model=dict, status_code=201)
async def quote_shipment(
    req: QuoteRequest,
    request: Request,
    # A0.2c dual-auth: acepta JWT user (Tenant Console) o INTERNAL_SERVICE_SECRET
    # header + X-Tenant-Id (orchestrator → api).
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
    supabase: Client = Depends(get_service_client_internal_or_user),
    _role: str = Depends(require_write_internal_or_user),
    _plan: object = Depends(PLAN_SHIPPING_QUOTE),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cotiza un envío via Aveonline (provider único activo, ADR-0019) y
    guarda el resultado en shipments. Retorna opciones de carrier/tarifa.
    """
    idem_session = None
    try:
        request_hash = payload_fingerprint(req.model_dump(mode="json"))
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        # Cotizador respeta active_provider del tenant.
        active_provider = _get_active_shipping_provider(tenant_id, supabase)
        if active_provider == "aveonline":
            response_body = await _quote_via_aveonline(tenant_id, supabase, req)
            finalize_idempotency(
                supabase=supabase,
                tenant_id=tenant_id,
                session=idem_session,
                status_code=201,
                body=response_body,
            )
            return response_body

        # Provider no soportado (Envia eliminado rev. 109 — ver ADR-0019).
        # Cuando se agregue Courier N+1 seguir ADR-0023.
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider shipping '{active_provider}' no soportado. Provider activo: "
                f"'aveonline'. Ve a /dashboard/integrations/aveonline para configurarlo."
            ),
        )
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as exc:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error inesperado cotizando envío tenant %s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error inesperado cotizando envío")


class RateSelection(BaseModel):
    carrier:           str
    service:           str
    total_price:       float
    currency:          str = "COP"
    delivery_date:     Optional[str] = None
    carrierId:         Optional[str] = None
    serviceId:         Optional[str] = None
    carrier_code:      Optional[str] = None
    service_code:      Optional[str] = None


# Nota rev. 109: Modelos LabelCreateRequest, TrackingRequest, PickupRequest,
# CancelShipmentRequest eliminados con endpoints /label, /tracking, /pickup,
# /cancel (eran Envia Fase 2, ADR-0019 superseded por Aveonline).
# Aveonline maneja:
#   - Label: implícito en `generarGuia2` post-confirmar orden
#   - Tracking: webhook estados en `aveonline_webhook.py`
#   - Pickup / Cancel: agendado via API Aveonline si se necesita (no via Konvi hoy)


@router.patch("/{shipment_id}/rate", response_model=dict)
async def confirm_rate(
    shipment_id: str,
    rate: RateSelection,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _plan: object = Depends(PLAN_SHIPPING_CONFIRM_RATE),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Confirma la tarifa seleccionada para un envío ya cotizado.
    Actualiza selected_rate, carrier, service, estimated_delivery.
    Si el envío tiene order_id, sincroniza shipping_cost en la orden.
    """
    idem_session = None
    try:
        request_hash = payload_fingerprint({
            "shipment_id": shipment_id,
            "rate": rate.model_dump(mode="json"),
        })
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        result = (
            supabase.table("shipments")
            .select("id, order_id, status")
            .eq("id", shipment_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        if result.data["status"] != "quoted":
            raise HTTPException(status_code=400, detail="Solo se puede confirmar tarifa en estado 'quoted'")

        update = {
            "selected_rate":      rate.model_dump(exclude_none=True),
            "carrier":            rate.carrier,
            "service":            rate.service,
            "estimated_delivery": rate.delivery_date,
        }
        supabase.table("shipments").update(update).eq("id", shipment_id).eq("tenant_id", tenant_id).execute()

        order_id = result.data.get("order_id")
        if order_id:
            supabase.table("orders").update(
                {"shipping_cost": rate.total_price}
            ).eq("id", order_id).eq("tenant_id", tenant_id).execute()

        response_body = {"ok": True}
        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=200,
            body=response_body,
        )
        return response_body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as exc:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error confirmando tarifa shipment %s tenant %s: %s", shipment_id, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error al confirmar tarifa")




@router.delete("/orphans", response_model=dict)
async def purge_orphan_quotes(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Elimina cotizaciones con status='quoted' sin tarifa seleccionada
    creadas hace más de 30 días. Libera espacio en DB.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    result = (
        supabase.table("shipments")
        .delete()
        .eq("tenant_id", tenant_id)
        .eq("status", "quoted")
        .is_("selected_rate", "null")
        .lt("created_at", cutoff)
        .execute()
    )
    deleted = len(result.data) if result.data else 0
    logger.info("Purged %d orphan quotes for tenant %s", deleted, tenant_id)
    return {"deleted": deleted}
