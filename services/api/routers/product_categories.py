"""CRUD de categorías de producto per-tenant (ADR-0027 Pieza 1 — categoría OPERATIVA).

Cierra el gap de la auditoría 2026-06-29: el bot usa `product_categories` (data-driven) pero NO
existía endpoint para que el operador las gestione (las de KAIU se curaron por script). Esta es la
"puerta" para que el Tenant Console cure las categorías que el bot presenta.

NO confundir con `platform_categories` (taxonomía GLOBAL de marketplace) — son dos capas distintas
con roles distintos (ver ADR-0027 REVISIÓN 2026-06-27).
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Product Categories"])


class ProductCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="Clave normalizada (única por tenant)")
    display_label: str = Field(..., min_length=1, max_length=120, description="Etiqueta visible al cliente")
    sort_order: int = Field(default=0, ge=0)
    parent_id: Optional[str] = None   # F2: categoría padre (jerarquía Categoría›Subcategoría). NULL = raíz/vertical.


class ProductCategoryPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    display_label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    sort_order: Optional[int] = Field(default=None, ge=0)
    parent_id: Optional[str] = None   # F2: reasignar padre (o mover a raíz enviando null explícito)


@router.get("/", response_model=List[dict])
async def list_product_categories(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista las categorías per-tenant ordenadas, con el conteo de productos activos en cada una."""
    try:
        cats = (
            supabase.table("product_categories")
            .select("id, name, display_label, sort_order, parent_id, created_at")
            .eq("tenant_id", tenant_id)
            .order("sort_order")
            .order("display_label")
            .execute()
        ).data or []

        # Conteo de productos activos por categoría (una sola query, agrupado en Python).
        prods = (
            supabase.table("products")
            .select("category_id")
            .eq("tenant_id", tenant_id)
            .eq("status", "active")
            .execute()
        ).data or []
        counts: dict = {}
        for p in prods:
            cid = p.get("category_id")
            if cid:
                counts[cid] = counts.get(cid, 0) + 1
        for c in cats:
            c["product_count"] = counts.get(c["id"], 0)
        return cats
    except Exception as e:
        logger.error("Error listando categorías tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener categorías") from e


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="product_category", action="created")
async def create_product_category(
    category: ProductCategoryCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea una categoría per-tenant. Solo owner/manager. `name` único por tenant."""
    try:
        # F2: validar el padre (si hay) — debe ser del tenant y ser RAÍZ (jerarquía máx 2 niveles).
        if category.parent_id:
            parent = (
                supabase.table("product_categories")
                .select("id, parent_id")
                .eq("id", category.parent_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if not parent.data:
                raise HTTPException(status_code=422, detail="Categoría padre inválida para este tenant")
            if parent.data[0].get("parent_id"):
                raise HTTPException(status_code=422, detail="Solo 2 niveles: la categoría padre ya es una subcategoría")
        result = supabase.table("product_categories").insert({
            "tenant_id": tenant_id,
            "name": category.name,
            "display_label": category.display_label,
            "sort_order": category.sort_order,
            "parent_id": category.parent_id,
        }).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear categoría")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        # UNIQUE(tenant_id, name) → 23505 si duplicado.
        if "23505" in str(e) or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre") from e
        logger.error("Error creando categoría tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear categoría") from e


@router.patch("/{category_id}", response_model=dict)
@audit_log(entity_type="product_category", action="updated")
async def patch_product_category(
    category_id: str,
    category: ProductCategoryPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita display_label / sort_order / name de una categoría. Solo owner/manager."""
    try:
        # exclude_unset: solo parcheamos lo que el cliente envió (permite parent_id=null explícito → mover a raíz,
        # sin que se cuele name/sort_order en null). Las server actions arman el body selectivamente.
        data = category.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")
        # F2: reasignar padre — validar tenant + raíz + no auto-referencia (jerarquía máx 2 niveles).
        new_parent = data.get("parent_id")
        if new_parent:
            if new_parent == category_id:
                raise HTTPException(status_code=422, detail="Una categoría no puede ser su propio padre")
            parent = (
                supabase.table("product_categories")
                .select("id, parent_id")
                .eq("id", new_parent)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if not parent.data:
                raise HTTPException(status_code=422, detail="Categoría padre inválida para este tenant")
            if parent.data[0].get("parent_id"):
                raise HTTPException(status_code=422, detail="Solo 2 niveles: la categoría padre ya es una subcategoría")
            # …ni anidar una categoría que YA es padre (tiene subcategorías) → crearía un 3er nivel.
            kids = (
                supabase.table("product_categories")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("parent_id", category_id)
                .limit(1)
                .execute()
            )
            if kids.data:
                raise HTTPException(status_code=422, detail="Esta categoría ya tiene subcategorías; no puede volverse subcategoría de otra")
        result = (
            supabase.table("product_categories")
            .update(data)
            .eq("id", category_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        if "23505" in str(e) or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre") from e
        logger.error("Error editando categoría %s: %s", category_id, e)
        raise HTTPException(status_code=500, detail="Error al editar categoría") from e


@router.delete("/{category_id}", response_model=dict)
@audit_log(entity_type="product_category", action="deleted")
async def delete_product_category(
    category_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Elimina una categoría. Los productos que la usaban quedan sin categoría
    (products.category_id ON DELETE SET NULL → fallback a heurística título-head). Solo owner/manager."""
    try:
        result = (
            supabase.table("product_categories")
            .delete()
            .eq("id", category_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        return {"deleted": True, "id": category_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando categoría %s: %s", category_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar categoría") from e
