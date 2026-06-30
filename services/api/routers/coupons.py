"""CRUD de cupones per-tenant — escrituras auditadas (F2.2 / auditoría 2026-06-29).

Cierra el gap de las escrituras directas de Promociones: crear/editar/activar/eliminar cupones
escribía directo a Supabase (RLS) SIN @audit_log. Ahora pasa por la API → traza forense de cambios de
precio (integridad comercial + Habeas Data) + RBAC server-side. La LECTURA sigue directa (RLS).

`code` es inmutable tras crear. DELETE condicional: solo hard-delete si el cupón nunca tuvo
redenciones (preserva auditoría); si tuvo, 409 → el operador debe desactivarlo (is_active=false).
Re-verificación server-side del conteo (anti-race). Validación espeja validateCouponInput del web.
"""
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    _extract_jwt_payload,
    get_current_tenant,
    get_service_client,
    require_write_role,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Coupons"])

_VALID_DISCOUNT_TYPES = {"percent", "fixed_amount", "free_shipping"}
_CODE_RE = re.compile(r"^[A-Z0-9_-]{3,30}$")


class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str
    discount_value: int = Field(default=0)
    min_subtotal_cents: int = Field(default=0)
    max_redemptions: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_customer_visible: bool = True


class CouponPatch(BaseModel):
    # NO incluye `code` — inmutable tras crear (igual que updateCouponAction del web).
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[int] = None
    min_subtotal_cents: Optional[int] = None
    max_redemptions: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_active: Optional[bool] = None
    is_customer_visible: Optional[bool] = None


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _validate_amounts(d: dict) -> Optional[str]:
    dt = d.get("discount_type")
    dv = d.get("discount_value")
    if dv is not None:
        if dv < 0:
            return "Valor del descuento no puede ser negativo."
        if dt == "percent" and dv > 100:
            return "Porcentaje no puede ser mayor a 100."
    msc = d.get("min_subtotal_cents")
    if msc is not None and msc < 0:
        return "Mínimo de subtotal no puede ser negativo."
    mr = d.get("max_redemptions")
    if mr is not None and mr <= 0:
        return "Máximo de redenciones debe ser positivo (o vacío para ilimitado)."
    return None


def _validate_dates(vf: Optional[str], vu: Optional[str]) -> Optional[str]:
    if vf and vu:
        try:
            if _parse_iso(vu) <= _parse_iso(vf):
                return "Fecha de fin debe ser posterior a fecha de inicio."
        except (ValueError, TypeError):
            return None  # formato no-ISO → la DB valida
    return None


def validate_coupon(d: dict, *, require_code: bool) -> Optional[str]:
    """Espeja validateCouponInput (web). Devuelve mensaje de error o None. Valida solo los campos
    presentes para soportar PATCH parcial / toggle is_active."""
    if require_code and not _CODE_RE.match(d.get("code") or ""):
        return "Código debe tener 3-30 caracteres mayúsculas/dígitos/-/_"
    dt = d.get("discount_type")
    if dt is not None and dt not in _VALID_DISCOUNT_TYPES:
        return "Tipo de descuento inválido."
    return _validate_amounts(d) or _validate_dates(d.get("valid_from"), d.get("valid_until"))


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="coupon", action="created")
async def create_coupon(
    coupon: CouponCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea un cupón. Solo owner/manager. `code` único por tenant (409 si duplicado)."""
    code = (coupon.code or "").strip().upper()
    payload = coupon.model_dump()
    payload["code"] = code
    err = validate_coupon(payload, require_code=True)
    if err:
        raise HTTPException(status_code=400, detail=err)
    try:
        created_by = (_extract_jwt_payload(request) or {}).get("sub")
        result = supabase.table("coupons").insert({
            "tenant_id": tenant_id,
            "code": code,
            "description": coupon.description,
            "discount_type": coupon.discount_type,
            "discount_value": coupon.discount_value,
            "min_subtotal_cents": coupon.min_subtotal_cents,
            "max_redemptions": coupon.max_redemptions,
            "valid_from": coupon.valid_from,
            "valid_until": coupon.valid_until,
            "is_active": True,
            "is_customer_visible": coupon.is_customer_visible,
            "created_by": created_by,
        }).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear el cupón")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        if "23505" in str(e) or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail=f'Ya existe un cupón con código "{code}".') from e
        logger.error("Error creando cupón tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear el cupón") from e


@router.patch("/{coupon_id}", response_model=dict)
@audit_log(entity_type="coupon", action="updated")
async def patch_coupon(
    coupon_id: str,
    coupon: CouponPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita un cupón (incluye activar/desactivar y visibilidad). Solo owner/manager.
    NO cambia `code` (inmutable)."""
    data = dict(coupon.model_dump(exclude_unset=True))
    if not data:
        raise HTTPException(status_code=422, detail="No hay campos para actualizar")
    err = validate_coupon(data, require_code=False)
    if err:
        raise HTTPException(status_code=400, detail=err)
    try:
        result = (
            supabase.table("coupons")
            .update(data)
            .eq("id", coupon_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Cupón no encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando cupón %s: %s", coupon_id, e)
        raise HTTPException(status_code=500, detail="Error al editar el cupón") from e


@router.delete("/{coupon_id}", response_model=dict)
@audit_log(entity_type="coupon", action="deleted")
async def delete_coupon(
    coupon_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Elimina un cupón SOLO si nunca tuvo redenciones (preserva auditoría Habeas Data). Si tuvo,
    409 → el operador debe desactivarlo. Re-verificación server-side del conteo (anti-race)."""
    try:
        cnt = (
            supabase.table("coupon_redemptions")
            .select("id", count="exact")
            .eq("coupon_id", coupon_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if (cnt.count or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail=("Este cupón ya tuvo redenciones (clientes lo aplicaron). No se puede eliminar "
                        'para preservar auditoría Habeas Data. Usa "Desactivar" en su lugar.'),
            )
        result = (
            supabase.table("coupons")
            .delete()
            .eq("id", coupon_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Cupón no encontrado")
        return {"deleted": True, "id": coupon_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando cupón %s: %s", coupon_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar el cupón") from e
