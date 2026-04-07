"""
Router de Productos — CRUD completo con aislamiento multi-tenant via RLS.

Endpoints:
  GET    /api/v1/products/          — listar productos del tenant
  POST   /api/v1/products/          — crear producto
  GET    /api/v1/products/{id}      — obtener producto por ID
  PUT    /api/v1/products/{id}      — actualizar producto completo
  PATCH  /api/v1/products/{id}      — actualizar campos parciales
  DELETE /api/v1/products/{id}      — desactivar producto (soft delete)

Seguridad:
  - Cada operación filtra explícitamente por tenant_id (defensa en profundidad)
  - RLS en Supabase es la barrera final (app_current_tenant())
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Products"])


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    sku: Optional[str] = None
    stock_quantity: int = Field(default=0, ge=0)
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    sku: Optional[str] = None
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    id: str
    tenant_id: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_products(
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Lista los productos del tenant autenticado.
    Soporta filtro por is_active y paginación.
    """
    try:
        query = (
            supabase.table("products")
            .select("id, name, description, price, sku, stock_quantity, is_active, created_at")
            .eq("tenant_id", tenant_id)
            .order("name")
            .limit(limit)
            .offset(offset)
        )
        if is_active is not None:
            query = query.eq("is_active", is_active)

        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error("Error listando productos para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener productos")


@router.post("/", response_model=dict, status_code=201)
async def create_product(
    product: ProductCreate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Crea un nuevo producto para el tenant autenticado."""
    try:
        data = product.model_dump()
        data["tenant_id"] = tenant_id

        result = supabase.table("products").insert(data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear producto")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creando producto para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear producto")


@router.get("/{product_id}", response_model=dict)
async def get_product(
    product_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna un producto por ID, validando que pertenece al tenant."""
    try:
        result = (
            supabase.table("products")
            .select("*")
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


@router.put("/{product_id}", response_model=dict)
async def update_product(
    product_id: str,
    product: ProductCreate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Actualiza todos los campos de un producto."""
    try:
        data = product.model_dump()
        result = (
            supabase.table("products")
            .update(data)
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado o sin cambios")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar producto")


@router.patch("/{product_id}", response_model=dict)
async def partial_update_product(
    product_id: str,
    product: ProductUpdate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Actualiza solo los campos provistos (PATCH semántico)."""
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
            raise HTTPException(status_code=404, detail="Producto no encontrado o sin cambios")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error en PATCH producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar producto")


@router.delete("/{product_id}", status_code=204)
async def deactivate_product(
    product_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Soft delete: marca el producto como inactivo (is_active=False).
    No elimina el registro para mantener trazabilidad de pedidos históricos.
    """
    try:
        result = (
            supabase.table("products")
            .update({"is_active": False})
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
