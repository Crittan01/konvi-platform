"""
Router de Productos — CRUD con aislamiento multi-tenant via RLS.

Schema real (migration 20260406181236_catalog_schema.sql):
  products:           id, tenant_id, title, description, status, external_reference_id
  product_variations: id, product_id, tenant_id, price, stock_quantity, attributes, external_variation_id

Endpoints:
  GET    /api/v1/products/                              — listar productos activos del tenant
  POST   /api/v1/products/                              — crear producto + variante inicial  [owner, manager]
  GET    /api/v1/products/{id}                          — obtener producto con variantes
  PATCH  /api/v1/products/{id}                          — editar título / descripción        [owner, manager]
  DELETE /api/v1/products/{id}                          — soft delete (status='inactive')    [owner, manager]
  PATCH  /api/v1/products/{id}/variations/{var_id}      — editar variante por ID             [owner, manager]
  POST   /api/v1/products/{id}/variations               — añadir variante a producto         [owner, manager]
  DELETE /api/v1/products/{id}/variations/{var_id}      — eliminar variante (no si es única) [owner, manager]

RBAC:
  owner / manager → lectura + escritura
  operator        → solo lectura (403 en escritura)

Nota: patch_variation dispara sync_meli_stock si stock_quantity cambia y hay listing activo.
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from routers.marketplace import sync_meli_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Products"])


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────

class VariationCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0)
    compare_at_price: Optional[float] = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    attributes: dict = Field(default={"default": "Standard"})
    weight_kg: Optional[float] = Field(default=None, ge=0)
    length_cm: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, ge=0)
    height_cm: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None


class ProductCreate(BaseModel):
    platform_category_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    variation: VariationCreate


class ProductPatch(BaseModel):
    platform_category_id: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    cover_image_url: Optional[str] = None


class VariationPatch(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    price: Optional[float] = Field(default=None, gt=0)
    compare_at_price: Optional[float] = Field(default=None, ge=0)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    attributes: Optional[dict] = None
    weight_kg: Optional[float] = Field(default=None, ge=0)
    length_cm: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, ge=0)
    height_cm: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None


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
            .select("id, title, description, status, platform_category_id, cover_image_url, created_at, product_variations(id, sku, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)")
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
@audit_log(entity_type="product", action="created")
async def create_product(
    product: ProductCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea producto + variante inicial. Solo owner/manager."""
    try:
        prod_result = supabase.table("products").insert({
            "tenant_id": tenant_id,
            "platform_category_id": product.platform_category_id,
            "title": product.title,
            "description": product.description,
            "cover_image_url": product.cover_image_url,
            "status": "active",
        }).execute()

        if not prod_result.data:
            raise HTTPException(status_code=500, detail="Error al crear producto")

        prod = prod_result.data[0]

        var_result = supabase.table("product_variations").insert({
            "product_id": prod["id"],
            "tenant_id": tenant_id,
            "sku": product.variation.sku,
            "price": product.variation.price,
            "compare_at_price": product.variation.compare_at_price,
            "stock_quantity": product.variation.stock_quantity,
            "attributes": product.variation.attributes,
            "weight_kg": product.variation.weight_kg,
            "length_cm": product.variation.length_cm,
            "width_cm": product.variation.width_cm,
            "height_cm": product.variation.height_cm,
            "image_url": product.variation.image_url,
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
            .select("id, title, description, status, platform_category_id, cover_image_url, created_at, product_variations(id, sku, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)")
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
@audit_log(entity_type="product", action="updated")
async def patch_product(
    product_id: str,
    product: ProductPatch,
    request: Request,
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


@router.patch("/{product_id}/variations/{variation_id}", response_model=dict)
@audit_log(entity_type="variation", action="updated")
async def patch_variation(
    product_id: str,
    variation_id: str,
    variation: VariationPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Edita precio, stock y/o atributos de una variante específica del producto.
    Requiere variation_id explícito — soporta productos multi-variante.
    Solo owner/manager.
    """
    try:
        data = {k: v for k, v in variation.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        # Verificar que la variante pertenece al producto y al tenant
        check = (
            supabase.table("product_variations")
            .select("id")
            .eq("id", variation_id)
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Variante no encontrada")

        result = (
            supabase.table("product_variations")
            .update(data)
            .eq("id", variation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Error al actualizar variante")

        # Si el stock cambió, sincronizar con MeLi en background (best-effort)
        if "stock_quantity" in data:
            asyncio.ensure_future(
                sync_meli_stock(variation_id, data["stock_quantity"], supabase)
            )

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando variante %s producto %s: %s", variation_id, product_id, e)
        raise HTTPException(status_code=500, detail="Error al editar variante")


@router.post("/{product_id}/variations", response_model=dict, status_code=201)
@audit_log(entity_type="variation", action="created")
async def add_variation(
    product_id: str,
    variation: VariationCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Añade una nueva variante a un producto existente.
    Permite agregar tallas, colores u otras dimensiones a productos ya creados.
    Solo owner/manager.
    """
    try:
        # Verificar que el producto pertenece al tenant
        prod_check = (
            supabase.table("products")
            .select("id")
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not prod_check.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        result = supabase.table("product_variations").insert({
            "product_id": product_id,
            "tenant_id": tenant_id,
            "sku": variation.sku,
            "price": variation.price,
            "compare_at_price": variation.compare_at_price,
            "stock_quantity": variation.stock_quantity,
            "attributes": variation.attributes,
            "weight_kg": variation.weight_kg,
            "length_cm": variation.length_cm,
            "width_cm": variation.width_cm,
            "height_cm": variation.height_cm,
            "image_url": variation.image_url,
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear variante")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error añadiendo variante a producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al añadir variante")


@router.delete("/{product_id}/variations/{variation_id}", status_code=204)
@audit_log(entity_type="variation", action="deleted")
async def delete_variation(
    product_id: str,
    variation_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Elimina una variante específica de un producto.
    No se puede eliminar si es la única variante del producto.
    Solo owner/manager.
    """
    try:
        # Verificar que no es la única variante
        count_result = (
            supabase.table("product_variations")
            .select("id")
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if len(count_result.data or []) <= 1:
            raise HTTPException(
                status_code=422,
                detail="No se puede eliminar la única variante del producto. Desactiva el producto si deseas retirarlo."
            )

        result = (
            supabase.table("product_variations")
            .delete()
            .eq("id", variation_id)
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Variante no encontrada")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando variante %s producto %s: %s", variation_id, product_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar variante")


@router.delete("/{product_id}", status_code=204)
@audit_log(entity_type="product", action="deleted")
async def deactivate_product(
    product_id: str,
    request: Request,
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
