"""
Router de Productos — CRUD con aislamiento multi-tenant via RLS.

Schema real (migration 20260406181236_catalog_schema.sql):
  products:           id, tenant_id, title, description, status, external_reference_id
  product_variations: id, product_id, tenant_id, price, stock_quantity, attributes, external_variation_id

Endpoints:
  GET    /api/v1/products/          — listar productos activos del tenant
  POST   /api/v1/products/          — crear producto + variante inicial  [owner, manager]
  GET    /api/v1/products/{id}      — obtener producto con variantes
  PATCH  /api/v1/products/{id}      — editar título / descripción         [owner, manager]
  DELETE /api/v1/products/{id}      — soft delete (status='inactive')     [owner, manager]

RBAC:
  owner / manager → lectura + escritura
  agent           → solo lectura (403 en escritura)
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Products"])


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────

class VariationCreate(BaseModel):
    price: float = Field(..., gt=0)
    stock_quantity: int = Field(default=0, ge=0)
    attributes: dict = Field(default={"default": "Standard"})


class ProductCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    variation: VariationCreate


class ProductPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None


class VariationPatch(BaseModel):
    price: Optional[float] = Field(default=None, gt=0)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    attributes: Optional[dict] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_products(
    status: Optional[str] = Query(default="active"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista productos del tenant con sus variantes. Por defecto solo activos."""
    try:
        query = (
            supabase.table("products")
            .select("id, title, description, status, created_at, product_variations(id, price, stock_quantity, attributes)")
            .eq("tenant_id", tenant_id)
            .order("title")
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            query = query.eq("status", status)

        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error("Error listando productos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener productos")


@router.post("/", response_model=dict, status_code=201)
async def create_product(
    product: ProductCreate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea producto + variante inicial. Solo owner/manager."""
    try:
        prod_result = supabase.table("products").insert({
            "tenant_id": tenant_id,
            "title": product.title,
            "description": product.description,
            "status": "active",
        }).execute()

        if not prod_result.data:
            raise HTTPException(status_code=500, detail="Error al crear producto")

        prod = prod_result.data[0]

        var_result = supabase.table("product_variations").insert({
            "product_id": prod["id"],
            "tenant_id": tenant_id,
            "price": product.variation.price,
            "stock_quantity": product.variation.stock_quantity,
            "attributes": product.variation.attributes,
        }).execute()

        prod["product_variations"] = var_result.data or []
        return prod
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creando producto tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear producto")


@router.get("/{product_id}", response_model=dict)
async def get_product(
    product_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna producto con variantes. Valida que pertenece al tenant."""
    try:
        result = (
            supabase.table("products")
            .select("id, title, description, status, created_at, product_variations(id, price, stock_quantity, attributes)")
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener producto")


@router.patch("/{product_id}", response_model=dict)
async def patch_product(
    product_id: str,
    product: ProductPatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita título y/o descripción del producto. Solo owner/manager."""
    try:
        data = {k: v for k, v in product.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        result = (
            supabase.table("products")
            .update(data)
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al editar producto")


@router.patch("/{product_id}/variation", response_model=dict)
async def patch_variation(
    product_id: str,
    variation: VariationPatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Edita precio y/o stock de la variante principal del producto.
    Actualiza la primera variante encontrada (modelo actual: 1 variante por producto).
    Gestión de variantes múltiples: deferred a Fase 9/11.
    """
    try:
        data = {k: v for k, v in variation.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        # Obtener la variante principal del producto
        var_result = (
            supabase.table("product_variations")
            .select("id")
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not var_result.data:
            raise HTTPException(status_code=404, detail="Variante no encontrada")

        variation_id = var_result.data[0]["id"]
        result = (
            supabase.table("product_variations")
            .update(data)
            .eq("id", variation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Error al actualizar variante")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando variante producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al editar variante")


@router.delete("/{product_id}", status_code=204)
async def deactivate_product(
    product_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Soft delete: marca el producto como 'inactive'.
    No elimina el registro para mantener trazabilidad histórica.
    Solo owner/manager.
    """
    try:
        result = (
            supabase.table("products")
            .update({"status": "inactive"})
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error desactivando producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al desactivar producto")
