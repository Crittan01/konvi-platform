"""CRUD del CONTRATO de atributos por categoría (ADR-0029 D3 — gobernanza de atributos tipados).

Cierra el gap F2: la validación HARD (products.py) y el seed existen, pero el contrato solo se podía
definir por SQL. Este router es la "puerta" para que el Tenant Console AUTORICE los atributos que guían
el alta y que el bot cita como HECHOS (SET membership, ADR-0024).

Fuente: product_attribute_definitions (per-tenant, FK a product_categories). NO confundir con
category_attributes/attribute_values (núcleo curado GLOBAL, capa distinta).

Patrón canónico (igual que product_categories.py): READ directo por RLS en el front; WRITE aquí con
RBAC (owner/manager) + @audit_log + tenant scoping + validación de ownership de la categoría.
"""
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Product Attribute Definitions"])

# Espejo del CHECK product_attribute_definitions_type_check.
_VALID_TYPES = {"select", "metric", "number", "boolean", "text"}


def _slugify(s: str) -> str:
    """Clave normalizada (code) desde el label: sin acentos, minúsculas, _ por no-alfanumérico."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "_", s.lower().strip())
    return re.sub(r"^_+|_+$", "", s)


class AttributeDefCreate(BaseModel):
    product_category_id: str = Field(..., description="Categoría (hoja) dueña del atributo")
    label: str = Field(..., min_length=1, max_length=120, description="Etiqueta visible (matching por label)")
    code: Optional[str] = Field(default=None, max_length=80, description="Clave; si falta se deriva del label")
    type: str = Field(..., description="select | metric | number | boolean | text")
    unit: Optional[str] = Field(default=None, max_length=20)
    is_required: bool = False
    is_variant_axis: bool = False
    allowed_values: List = Field(default_factory=list, description="Enum cerrado (select/metric); [] si libre")
    sort_order: int = Field(default=0, ge=0)


class AttributeDefPatch(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    type: Optional[str] = None
    unit: Optional[str] = Field(default=None, max_length=20)
    is_required: Optional[bool] = None
    is_variant_axis: Optional[bool] = None
    allowed_values: Optional[List] = None
    sort_order: Optional[int] = Field(default=None, ge=0)


def _assert_category_owned(supabase: Client, tenant_id: str, category_id: str) -> None:
    """La categoría del contrato DEBE pertenecer al tenant (integridad multi-tenant, ADR-0025)."""
    owned = (
        supabase.table("product_categories")
        .select("id")
        .eq("id", category_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not owned.data:
        raise HTTPException(status_code=422, detail="Categoría inválida para este tenant")


def _validate_type(t: str) -> None:
    if t not in _VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"Tipo inválido. Válidos: {', '.join(sorted(_VALID_TYPES))}")


@router.get("/", response_model=List[dict])
async def list_attribute_definitions(
    product_category_id: Optional[str] = None,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista las definiciones del contrato del tenant, opcionalmente filtradas por categoría."""
    try:
        q = (
            supabase.table("product_attribute_definitions")
            .select("id, product_category_id, code, label, type, unit, is_required, "
                    "is_variant_axis, allowed_values, sort_order, created_at")
            .eq("tenant_id", tenant_id)
        )
        if product_category_id:
            q = q.eq("product_category_id", product_category_id)
        return (q.order("sort_order").order("label").execute()).data or []
    except Exception as e:
        logger.error("Error listando defs de atributo tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener el contrato de atributos") from e


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="attribute_definition", action="created")
async def create_attribute_definition(
    definition: AttributeDefCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea una definición de atributo en el contrato de una categoría. Solo owner/manager."""
    try:
        _assert_category_owned(supabase, tenant_id, definition.product_category_id)
        _validate_type(definition.type)
        code = (definition.code or "").strip() or _slugify(definition.label)
        if not code:
            raise HTTPException(status_code=422, detail="No se pudo derivar un code válido del label")
        if not isinstance(definition.allowed_values, list):
            raise HTTPException(status_code=422, detail="allowed_values debe ser una lista")
        result = supabase.table("product_attribute_definitions").insert({
            "tenant_id": tenant_id,
            "product_category_id": definition.product_category_id,
            "code": code,
            "label": definition.label,
            "type": definition.type,
            "unit": definition.unit,
            "is_required": definition.is_required,
            "is_variant_axis": definition.is_variant_axis,
            "allowed_values": definition.allowed_values,
            "sort_order": definition.sort_order,
        }).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear la definición")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        # UNIQUE(tenant_id, product_category_id, code) → 23505 si duplicado.
        if "23505" in str(e) or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Ya existe un atributo con ese code en esta categoría") from e
        logger.error("Error creando def de atributo tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear la definición") from e


@router.patch("/{definition_id}", response_model=dict)
@audit_log(entity_type="attribute_definition", action="updated")
async def patch_attribute_definition(
    definition_id: str,
    definition: AttributeDefPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita una definición de atributo. Solo owner/manager. El code y la categoría no se reasignan aquí."""
    try:
        data = definition.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")
        if "type" in data:
            _validate_type(data["type"])
        if "allowed_values" in data and not isinstance(data["allowed_values"], list):
            raise HTTPException(status_code=422, detail="allowed_values debe ser una lista")
        result = (
            supabase.table("product_attribute_definitions")
            .update(data)
            .eq("id", definition_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Definición no encontrada")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando def %s: %s", definition_id, e)
        raise HTTPException(status_code=500, detail="Error al editar la definición") from e


@router.delete("/{definition_id}", status_code=204)
@audit_log(entity_type="attribute_definition", action="deleted")
async def delete_attribute_definition(
    definition_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Elimina una definición del contrato. Los valores ya persistidos en products.attributes NO se tocan
    (quedan como histórico; la validación solo aplica al contrato vigente en cada escritura). Solo owner/manager."""
    try:
        result = (
            supabase.table("product_attribute_definitions")
            .delete()
            .eq("id", definition_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Definición no encontrada")
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando def %s: %s", definition_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar la definición") from e
