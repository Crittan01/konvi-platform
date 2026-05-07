"""
Router de Shipping — Cotizaciones de envío via Envia.

Endpoints:
  POST /api/v1/shipping/quote          — cotizar envío via Envia          [owner, manager]
  PATCH /api/v1/shipping/{id}/rate     — confirmar tarifa seleccionada     [owner, manager]
  POST /api/v1/shipping/{id}/label     — generar label (Fase 2, flag)      [owner, manager]
  POST /api/v1/shipping/tracking       — consultar tracking (Fase 2, flag)
  POST /api/v1/shipping/pickup         — agendar pickup (Fase 2, flag)      [owner, manager]
  POST /api/v1/shipping/cancel         — cancelar envío (Fase 2, flag)      [owner, manager]
  DELETE /api/v1/shipping/orphans      — purgar cotizaciones huérfanas     [owner, manager]
  GET  /api/v1/shipping/history        — historial de cotizaciones

Prerequisito: tenant debe tener Envia conectado (status=connected en tenant_integrations).
Referencia de diseño: docs/integrations/courier-envia.md
"""
import asyncio
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional, List
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
from dependencies.plans import PLAN_SHIPPING_CONFIRM_RATE, PLAN_SHIPPING_QUOTE
from dependencies.security import RL_WRITE_DEFAULT
from integrations.envia_client import EnviaClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Shipping"])
ENVIA_PHASE2_ENABLED = os.getenv("ENVIA_PHASE2_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


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


def _normalize_country(country: Optional[str], default: str = "CO") -> str:
    """
    Normaliza país a formato operativo de Envia.
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
    """Convierte nombre largo de departamento al código corto que Envia acepta."""
    country_code = _normalize_country(country, default="CO")
    if country_code != "CO" or len(state) <= 3:
        return state
    return _CO_STATE_CODES.get(state, state[:3].upper())


# Rev. 72 — sanitización DANE centralizada en `dependencies/dane.py`.
# Aliases locales para no romper call-sites históricos en este módulo.
from dependencies.dane import sanitize_dane_code as _sanitize_dane_code, co_dane_codes as _co_dane_codes  # noqa: E402,F401


async def _validate_co_address_with_envia(_client: EnviaClient, addr: "Address", label: str) -> None:
    """
    Valida dirección de Colombia contra APIs oficiales de Envia antes de cotizar.
    Reglas runtime:
    - country=CO
    - dane_code de entrada aceptado en 5 u 8 dígitos
    - city/postalCode enviados a Shipping API en DANE 8 dígitos
    """
    addr.country = _normalize_country(addr.country, default="CO")
    dane5, dane8 = _co_dane_codes(addr.dane_code or addr.postalCode)
    if not dane5 or not dane8:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La dirección de {label} requiere código DANE válido (5 u 8 dígitos). "
                "Selecciona departamento y ciudad desde el formulario."
            ),
        )

    # Certificado en pruebas locales con token real (2026-04-20):
    # para varios carriers CO, DANE de 5 dígitos falla; DANE de 8 dígitos funciona.
    addr.dane_code = dane8
    addr.postalCode = dane8
    addr.state = _normalize_state(addr.state or "", addr.country) or addr.state


def _extract_carrier_name(item: dict) -> str:
    for key in ("name", "carrier", "code", "slug"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _resolve_carriers_for_quote(
    client: EnviaClient,
    country_code: str,
    *,
    supabase: Optional[Client] = None,
    tenant_id: Optional[str] = None,
) -> list[str]:
    """
    Prioriza Queries API para resolver carriers activos; si falla, usa fallback estable.

    Sem 5 H.2.7: si `supabase + tenant_id` provistos, filtra resultado
    final por las preferencias del tenant en `tenant_carriers`. Si el
    tenant NO configuró preferencias → todos enabled (backward compat).
    """
    carriers: list[str] = []
    try:
        dynamic = await client.get_available_carriers_with_shipment_type(
            country=country_code,
            international=0,
            shipment_type_id=1,
        )
        for row in dynamic:
            if not isinstance(row, dict):
                continue
            name = _extract_carrier_name(row)
            if name:
                carriers.append(name)
    except Exception as exc:
        logger.warning("No se pudo resolver carriers con Queries API (v2): %s", exc)

    if not carriers:
        try:
            legacy = await client.get_available_carriers(country=country_code, shipment_type=0)
            for row in legacy:
                if not isinstance(row, dict):
                    continue
                name = _extract_carrier_name(row)
                if name:
                    carriers.append(name)
        except Exception as exc:
            logger.warning("No se pudo resolver carriers con Queries API (legacy): %s", exc)

    # Fallback operativo conocido para CO (evita downtime si Queries API falla).
    if country_code == "CO" and not carriers:
        carriers = [
            "tcc", "serviEntrega", "coordinadora", "interRapidisimo",
            "deprisa", "mensajerosUrbanos", "noventa9Minutos",
            "fedex", "dhl", "envia",
        ]

    # dedupe preservando orden
    seen: set[str] = set()
    unique: list[str] = []
    for carrier in carriers:
        token = carrier.lower()
        if token not in seen:
            unique.append(carrier)
            seen.add(token)

    # Sem 5 H.2.7 — aplicar preferencias per-tenant si están provistas.
    if supabase is not None and tenant_id:
        try:
            from lib.tenant_carriers import filter_enabled_carriers
            filtered = filter_enabled_carriers(
                supabase, tenant_id, "envia", unique,
            )
            logger.info(
                "[CARRIERS] tenant=%s filtered %d → %d (preferencias DB)",
                tenant_id, len(unique), len(filtered),
            )
            return filtered
        except Exception as exc:
            logger.warning(
                "[CARRIERS] no se pudo aplicar filter tenant=%s: %s — "
                "devuelvo todos (default open)",
                tenant_id, exc,
            )
    return unique


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
    # Sem 5 H.2.5 — declaredValue per parcel para insurance.
    # Si el caller (orchestrator/cart_tool) lo provee con valor real
    # del cart subtotal, y el carrier elegido tiene supports_insurance
    # en tenant_carriers, el helper agrega additional_services:
    # ['envia_insurance'] al payload de Envia.
    # Coordinadora EXIGE este flag siempre per dossier sec. 4.
    declaredValueCop: Optional[int] = Field(
        default=None,
        ge=0,
        description="Valor declarado en pesos COP (NO cents). Si NULL, "
                    "no se aplica insurance independiente del carrier.",
    )


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
    from vault_helper import VaultHelper, resolve_secret
    api_token = resolve_secret(VaultHelper(supabase), creds, "api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="API token de Envia no encontrado")

    sandbox = creds.get("sandbox", False)
    return EnviaClient(api_token=api_token, sandbox=sandbox)


def _require_envia_phase2() -> None:
    """
    DEPRECADO post-rev. 105 Sem 5 H.2.6 — gate global env-var.
    Usar `_require_envia_capability(supabase, tenant_id, capability)`
    en su lugar para granularidad per-tenant per-capability.
    Mantenido como fallback temporal durante migración.
    """
    if not ENVIA_PHASE2_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "Shipping Fase 2 está deshabilitada en este entorno. "
                "Activa ENVIA_PHASE2_ENABLED=true para habilitar label/tracking/pickup/cancel."
            ),
        )


def _require_envia_capability(
    supabase: Client,
    tenant_id: str,
    capability: str,
) -> None:
    """
    Valida que el tenant tenga una capability Envia habilitada en
    `tenant_provider_capabilities` (F.3 matrix). Reemplaza el flag
    global env-var por gate granular per-tenant per-feature.

    Capabilities Envia válidas (ver `lib/capabilities_matrix.py`):
      - 'label_generation' — POST /shipments/{id}/label
      - 'tracking_polling' — POST /shipping/tracking
      - 'pickup'           — POST /shipments/{id}/schedule-pickup
      - 'cancel'           — POST /shipments/{id}/cancel
      - 'cod'              — futuro H.2.4
      - 'insurance'        — futuro H.2.5

    Backward compat: si el env var global ENVIA_PHASE2_ENABLED=true,
    se permite (durante migración). Tras seed inicial de capabilities
    para tenants existentes, este fallback se puede retirar.
    """
    from lib.capabilities_matrix import is_capability_enabled
    enabled = is_capability_enabled(
        supabase, tenant_id, "envia", capability, default=False,
    )
    if enabled:
        return
    # Fallback transición.
    if ENVIA_PHASE2_ENABLED:
        return
    raise HTTPException(
        status_code=503,
        detail=(
            f"Capability Envia '{capability}' deshabilitada para este tenant. "
            f"Actívala en Settings → Integraciones → Envia."
        ),
    )


def _parse_envia_label_data(raw: dict) -> dict:
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, list) and data:
        first = data[0] if isinstance(data[0], dict) else {}
    elif isinstance(data, dict):
        first = data
    else:
        first = {}

    tracking_number = (
        first.get("trackingNumber")
        or first.get("tracking_number")
        or first.get("guideNumber")
        or ""
    )
    tracking_url = first.get("trackingUrl") or first.get("trackUrl") or ""
    label_url = (
        first.get("label")
        or first.get("label_url")
        or first.get("labelUrl")
        or first.get("url")
        or ""
    )
    shipment_id = (
        first.get("shipmentId")
        or first.get("shipment_id")
        or first.get("id")
        or ""
    )
    return {
        "tracking_number": str(tracking_number or ""),
        "tracking_url": str(tracking_url or ""),
        "label_url": str(label_url or ""),
        "envia_shipment_id": str(shipment_id or ""),
    }


def _parse_envia_track_data(raw: dict) -> list[dict]:
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


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
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _plan: object = Depends(PLAN_SHIPPING_QUOTE),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cotiza un envío via Envia y guarda el resultado en shipments.
    Retorna las opciones de carrier/tarifa disponibles.
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

        client = _get_envia_client(tenant_id, supabase)

        # Normalización mínima de país
        req.origin.country = _normalize_country(req.origin.country, default="CO")
        req.destination.country = _normalize_country(req.destination.country, default="CO")

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
            country_code = _normalize_country(a.country, default="CO")
            d["country"] = country_code
            d["state"] = _normalize_state(a.state, country_code)
            if country_code == "CO" and a.dane_code:
                # Para Colombia: runtime efectivo en Envia usa DANE 8 dígitos (stat_8digit).
                d["city"]            = a.dane_code
                d["postalCode"]      = a.dane_code
            return d

        # Validación de direcciones CO contra APIs oficiales de Envia.
        # Mantiene alineación con contrato "city/postalCode = DANE".
        for label, addr in [("origen", req.origin), ("destino", req.destination)]:
            if addr.country == "CO":
                await _validate_co_address_with_envia(client, addr, label)

        base_payload = {
            "origin":      _addr(req.origin),
            "destination": _addr(req.destination),
            "packages":    packages,
            "settings":    {"currency": "COP"},
        }

        # Carriers activos: resolver desde Queries API; fallback seguro si el endpoint falla.
        # Sem 5 H.2.7: filtra por preferencias tenant_carriers per-tenant.
        quote_country = req.origin.country if req.origin.country == req.destination.country else "CO"
        carriers = await _resolve_carriers_for_quote(
            client, quote_country,
            supabase=supabase, tenant_id=tenant_id,
        )
        if not carriers:
            raise HTTPException(
                status_code=502,
                detail=(
                    "No se pudieron obtener carriers disponibles. "
                    "Verifica preferencias del tenant en Settings → Integraciones → Envia "
                    "(¿todos los carriers están desactivados?) o estado de Envia Queries API."
                ),
            )

        carrier_errors: dict[str, str] = {}
        logger.info(
            "Envia quote payload base (tenant %s): "
            "origin_state=%s origin_city=%s origin_postal=%s | "
            "dest_state=%s dest_city=%s dest_postal=%s",
            tenant_id,
            base_payload.get("origin", {}).get("state"),
            base_payload.get("origin", {}).get("city"),
            base_payload.get("origin", {}).get("postalCode"),
            base_payload.get("destination", {}).get("state"),
            base_payload.get("destination", {}).get("city"),
            base_payload.get("destination", {}).get("postalCode"),
        )

        # Sem 5 H.2.5 — declaredValue total (suma de parcels) para insurance.
        total_declared_value_cop = sum(
            int(p.declaredValueCop or 0) for p in req.parcels
        )

        async def _fetch_carrier(carrier: str):
            # Sem 5 H.2.5 — apply insurance per-carrier según preferencias.
            carrier_packages = packages
            try:
                from lib.insurance import (
                    should_apply_insurance, apply_insurance_to_packages,
                )
                if total_declared_value_cop > 0 and should_apply_insurance(
                    supabase, tenant_id, carrier,
                ):
                    carrier_packages = apply_insurance_to_packages(
                        packages, declared_value_cop=total_declared_value_cop,
                    )
                    logger.info(
                        "[INSURANCE] tenant=%s carrier=%s declared=%s aplicado",
                        tenant_id, carrier, total_declared_value_cop,
                    )
            except Exception as exc:
                logger.warning(
                    "[INSURANCE] no se pudo aplicar tenant=%s carrier=%s: %s — "
                    "cotización sigue sin seguro",
                    tenant_id, carrier, exc,
                )

            payload = {
                **base_payload,
                "packages": carrier_packages,
                "shipment": {"carrier": carrier, "type": 1},
            }
            for attempt in range(2):
                try:
                    resp = await client.get_rates(payload)
                    data = resp.get("data") if isinstance(resp, dict) else resp
                    return data if isinstance(data, list) else []
                except Exception as exc:
                    err_text = str(exc).strip() or repr(exc)
                    if attempt == 0:
                        logger.warning("Envia carrier %s reintentando... (tenant %s): %s", carrier, tenant_id, err_text)
                        await asyncio.sleep(1)
                    else:
                        carrier_errors[carrier] = err_text
                        logger.warning("Envia carrier %s falló (tenant %s): %s", carrier, tenant_id, err_text)
            return []

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch_carrier(c) for c in carriers]),
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
            error_sample = next(iter(carrier_errors.values()), None) if carrier_errors else None
            if error_sample:
                logger.warning(
                    "Envia no retorno tarifas tenant=%s; sample_error=%s",
                    tenant_id,
                    error_sample,
                )
            raise HTTPException(
                status_code=502,
                detail="Envia no retornó tarifas en este momento. Intenta nuevamente en unos minutos.",
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

        # Guardar cotización en shipments — quote_response no se persiste (tarifas son efímeras)
        shipment_result = supabase.table("shipments").insert({
            "tenant_id":           tenant_id,
            "order_id":            req.order_id,
            "status":              "quoted",
            "origin_address":      req.origin.model_dump(exclude_none=True),
            "destination_address": req.destination.model_dump(exclude_none=True),
            "parcels":             [p.model_dump() for p in req.parcels],
        }).execute()

        shipment_id = shipment_result.data[0]["id"] if shipment_result.data else None

        response_body = {
            "shipment_id": shipment_id,
            "rates":       normalized_rates,
            "highlights":  _build_rate_highlights(normalized_rates),
        }
        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=201,
            body=response_body,
        )
        return response_body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as exc:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error inesperado cotizando Envia tenant %s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error inesperado cotizando envío")


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


class LabelCreateRequest(BaseModel):
    # Si no viene carrier/service en el body, se toma de selected_rate.
    carrier: Optional[str] = None
    service: Optional[str] = None
    carrier_code: Optional[str] = None
    service_code: Optional[str] = None
    save_selected_rate: bool = True


class TrackingRequest(BaseModel):
    shipment_id: Optional[str] = None
    tracking_numbers: List[str] = Field(default_factory=list, min_length=0)


class PickupRequest(BaseModel):
    shipment_id: str
    date: str = Field(..., description="YYYY-MM-DD")
    time_from: str = Field(..., description="HH:mm")
    time_to: str = Field(..., description="HH:mm")
    total_weight: Optional[float] = Field(default=None, gt=0)
    instructions: Optional[str] = Field(default=None, max_length=500)


class CancelShipmentRequest(BaseModel):
    shipment_id: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    folio: Optional[str] = None
    ecommerce: Optional[int] = None


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


@router.post("/{shipment_id}/label", response_model=dict)
async def generate_label(
    shipment_id: str,
    body: LabelCreateRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Genera etiqueta para un shipment cotizado usando selected_rate o payload explícito.
    """
    _require_envia_capability(supabase, tenant_id, "label_generation")
    try:
        row = (
            supabase.table("shipments")
            .select("id, tenant_id, status, order_id, origin_address, destination_address, parcels, selected_rate")
            .eq("id", shipment_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        shipment = row.data
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment no encontrado")

        selected = shipment.get("selected_rate") or {}
        carrier = body.carrier_code or body.carrier or selected.get("carrier_code") or selected.get("carrier")
        service = body.service_code or body.service or selected.get("service_code") or selected.get("service")
        if not carrier or not service:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Falta carrier/service para generar label. "
                    "Confirma una tarifa primero o envía carrier/service explícitos."
                ),
            )

        origin = shipment.get("origin_address") or {}
        destination = shipment.get("destination_address") or {}
        parcels = shipment.get("parcels") or []
        if not isinstance(parcels, list) or not parcels:
            raise HTTPException(status_code=422, detail="Shipment sin parcels para generar label.")

        packages = [
            {
                "weight": p.get("weight"),
                "dimensions": {
                    "length": p.get("length"),
                    "width": p.get("width"),
                    "height": p.get("height"),
                },
                "content": p.get("content") or "Mercancía general",
                "amount": p.get("amount") or 1,
                "type": "box",
                "declaredValue": 0,
                "lengthUnit": "CM",
                "weightUnit": "KG",
            }
            for p in parcels
            if isinstance(p, dict)
        ]

        payload = {
            "origin": origin,
            "destination": destination,
            "packages": packages,
            "shipment": {
                "carrier": carrier,
                "service": service,
                "type": 1,
            },
            "settings": {"currency": "COP"},
        }

        client = _get_envia_client(tenant_id, supabase)
        raw = await client.generate_label(payload)
        parsed = _parse_envia_label_data(raw)

        update_payload = {
            "status": "labeled",
            "carrier": selected.get("carrier") or carrier,
            "service": selected.get("service") or service,
            "tracking_number": parsed["tracking_number"] or None,
            "tracking_url": parsed["tracking_url"] or None,
            "label_url": parsed["label_url"] or None,
            "envia_shipment_id": parsed["envia_shipment_id"] or None,
        }
        if body.save_selected_rate and selected:
            update_payload["selected_rate"] = selected

        (
            supabase.table("shipments")
            .update(update_payload)
            .eq("id", shipment_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        order_id = shipment.get("order_id")
        external_id = parsed["envia_shipment_id"] or parsed["tracking_number"] or shipment_id
        if order_id:
            (
                supabase.table("order_tracking")
                .upsert(
                    {
                        "tenant_id": tenant_id,
                        "order_id": order_id,
                        "provider": "envia",
                        "external_id": external_id,
                        "status": "labeled",
                        "tracking_number": parsed["tracking_number"] or None,
                        "tracking_url": parsed["tracking_url"] or None,
                        "carrier": selected.get("carrier") or carrier,
                        "raw": raw,
                    },
                    on_conflict="tenant_id,provider,external_id",
                )
                .execute()
            )

        return {
            "ok": True,
            "shipment_id": shipment_id,
            "tracking_number": parsed["tracking_number"] or None,
            "tracking_url": parsed["tracking_url"] or None,
            "label_url": parsed["label_url"] or None,
            "raw": raw,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error generando label shipment %s tenant %s: %s", shipment_id, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error al generar label de envío")


@router.post("/tracking", response_model=dict)
async def track_shipments(
    body: TrackingRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Consulta tracking en Envia por shipment_id o tracking_numbers.
    """
    _require_envia_capability(supabase, tenant_id, "tracking_polling")
    tracking_numbers = [n.strip() for n in body.tracking_numbers if isinstance(n, str) and n.strip()]

    shipment = None
    if body.shipment_id:
        row = (
            supabase.table("shipments")
            .select("id, tenant_id, tracking_number, order_id")
            .eq("id", body.shipment_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        shipment = row.data
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment no encontrado")
        if shipment.get("tracking_number"):
            tracking_numbers.append(str(shipment["tracking_number"]))

    dedup = []
    seen = set()
    for number in tracking_numbers:
        if number not in seen:
            dedup.append(number)
            seen.add(number)
    if not dedup:
        raise HTTPException(status_code=422, detail="Debes enviar shipment_id con tracking_number o tracking_numbers.")

    try:
        client = _get_envia_client(tenant_id, supabase)
        raw = await client.track_shipments(dedup)
        events = _parse_envia_track_data(raw)

        if shipment and events:
            first = events[0]
            status = str(first.get("status") or first.get("statusDescription") or "").strip() or None
            tracking_url = str(first.get("trackingUrl") or first.get("trackUrl") or "").strip() or None
            (
                supabase.table("shipments")
                .update(
                    {
                        **({"status": status.lower().replace(" ", "_")} if status else {}),
                        **({"tracking_url": tracking_url} if tracking_url else {}),
                    }
                )
                .eq("id", shipment["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            order_id = shipment.get("order_id")
            if order_id:
                external_id = str(first.get("trackingNumber") or shipment.get("tracking_number") or shipment["id"])
                (
                    supabase.table("order_tracking")
                    .upsert(
                        {
                            "tenant_id": tenant_id,
                            "order_id": order_id,
                            "provider": "envia",
                            "external_id": external_id,
                            "status": status,
                            "tracking_number": first.get("trackingNumber") or shipment.get("tracking_number"),
                            "tracking_url": tracking_url,
                            "carrier": first.get("carrier"),
                            "raw": first,
                        },
                        on_conflict="tenant_id,provider,external_id",
                    )
                    .execute()
                )

        return {"ok": True, "tracking_numbers": dedup, "events": events, "raw": raw}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error consultando tracking Envia tenant %s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error consultando tracking de envío")


@router.post("/pickup", response_model=dict)
async def schedule_pickup(
    body: PickupRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Agenda pickup de un shipment etiquetado.
    """
    _require_envia_capability(supabase, tenant_id, "pickup")
    row = (
        supabase.table("shipments")
        .select("id, tenant_id, origin_address, tracking_number, carrier")
        .eq("id", body.shipment_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    shipment = row.data
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment no encontrado")
    if not shipment.get("tracking_number"):
        raise HTTPException(status_code=422, detail="Shipment sin tracking_number para pickup.")
    if not shipment.get("carrier"):
        raise HTTPException(status_code=422, detail="Shipment sin carrier para pickup.")

    total_weight = body.total_weight if body.total_weight is not None else 1.0
    payload = {
        "origin": shipment.get("origin_address") or {},
        "shipment": {
            "carrier": shipment.get("carrier"),
            "pickup": {
                "date": body.date,
                "from": body.time_from,
                "to": body.time_to,
                "trackingNumbers": [shipment.get("tracking_number")],
                "totalWeight": total_weight,
                **({"instructions": body.instructions} if body.instructions else {}),
            },
        },
    }

    try:
        client = _get_envia_client(tenant_id, supabase)
        raw = await client.schedule_pickup(payload)
        return {"ok": True, "shipment_id": body.shipment_id, "raw": raw}
    except Exception as exc:
        logger.error("Error agendando pickup shipment %s tenant %s: %s", body.shipment_id, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error al agendar pickup")


@router.post("/cancel", response_model=dict)
async def cancel_shipment(
    body: CancelShipmentRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cancela un envío etiquetado por tracking_number o shipment_id.
    """
    _require_envia_capability(supabase, tenant_id, "cancel")

    tracking_number = (body.tracking_number or "").strip()
    carrier = (body.carrier or "").strip()
    shipment_id = (body.shipment_id or "").strip()

    if shipment_id and (not tracking_number or not carrier):
        row = (
            supabase.table("shipments")
            .select("id, tenant_id, tracking_number, carrier")
            .eq("id", shipment_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        shipment = row.data
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment no encontrado")
        tracking_number = tracking_number or str(shipment.get("tracking_number") or "")
        carrier = carrier or str(shipment.get("carrier") or "")

    if not tracking_number or not carrier:
        raise HTTPException(
            status_code=422,
            detail="Debes enviar tracking_number y carrier, o shipment_id con ambos campos persistidos.",
        )

    try:
        client = _get_envia_client(tenant_id, supabase)
        raw = await client.cancel_shipment(
            carrier=carrier,
            tracking_number=tracking_number,
            folio=body.folio,
            ecommerce=body.ecommerce,
        )
        if shipment_id:
            (
                supabase.table("shipments")
                .update({"status": "cancelled"})
                .eq("id", shipment_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        return {"ok": True, "tracking_number": tracking_number, "carrier": carrier, "raw": raw}
    except Exception as exc:
        logger.error("Error cancelando shipment tracking=%s tenant %s: %s", tracking_number, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error al cancelar envío")


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
