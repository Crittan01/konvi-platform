"""Catálogo canónico cross-surface (ADR-0028 Pieza B).

GET /api/v1/catalog — emite el catálogo del tenant en la FORMA CANÓNICA customer-facing que
cualquier superficie (bot, web, storefront, marketplace futuro) puede consumir SIN reimplementar
la verdad: producto + variantes bajo la clave `variants` (misma constante que el bot,
`catalog_contract.CATALOG_VARIATIONS_KEY`), con la categoría OPERATIVA (product_categories,
ADR-0027) y safety_note (Ley 1480). NUNCA expone cost_price (interno) — el contrato es cara-cliente.

Hoy el bot lee el catálogo in-process (hot path); este endpoint es la puerta para que web/futuras
superficies consuman la MISMA forma. Test de pacto: tests/test_catalog_canonical_contract.py.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Catalog"])

# Clave canónica de variantes — DEBE coincidir con
# services/ai-orchestrator/tools/catalog_contract.CATALOG_VARIATIONS_KEY (el pact lo fuerza).
CATALOG_VARIATIONS_KEY = "variants"


def shape_catalog_product(p: dict, category_label: Optional[str]) -> dict:
    """Producto en la forma canónica customer-facing. SIN cost_price (interno)."""
    variants = []
    for v in (p.get("product_variations") or []):
        attrs = v.get("attributes") if isinstance(v.get("attributes"), dict) else {}
        label = " / ".join(str(x) for x in attrs.values()) if attrs else (v.get("sku") or "")
        variants.append({
            "id": v.get("id"),
            "sku": v.get("sku"),
            "label": label,
            "price": v.get("price"),
            "currency": "COP",
            "stock": v.get("stock_quantity"),
            "image_url": v.get("image_url"),
            "attributes": attrs,
        })
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "description": p.get("description"),
        "safety_note": p.get("safety_note"),
        "retracto_excluded": p.get("retracto_excluded"),
        "category": category_label,
        "category_id": p.get("category_id"),
        "cover_image_url": p.get("cover_image_url"),
        CATALOG_VARIATIONS_KEY: variants,
    }


@router.get("/", response_model=List[dict])
async def get_catalog(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Catálogo canónico del tenant (productos activos + variantes), forma cross-surface."""
    try:
        prods = (
            supabase.table("products")
            .select(
                "id, title, description, safety_note, retracto_excluded, category_id, "
                "cover_image_url, product_variations(id, sku, price, stock_quantity, "
                "attributes, image_url)"
            )
            .eq("tenant_id", tenant_id)
            .eq("status", "active")
            .order("title")
            .limit(limit)
            .offset(offset)
            .execute()
        ).data or []

        # Mapa categoría operativa id→display_label (ADR-0027).
        cats = (
            supabase.table("product_categories")
            .select("id, display_label")
            .eq("tenant_id", tenant_id)
            .execute()
        ).data or []
        cat_label = {c["id"]: c["display_label"] for c in cats}

        return [shape_catalog_product(p, cat_label.get(p.get("category_id"))) for p in prods]
    except Exception as e:
        logger.error("Error catálogo canónico tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener el catálogo") from e


@router.get("/categories", response_model=List[dict])
async def get_catalog_categories(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Categorías operativas del tenant (para navegación cross-surface)."""
    try:
        cats = (
            supabase.table("product_categories")
            .select("id, name, display_label, sort_order")
            .eq("tenant_id", tenant_id)
            .order("sort_order")
            .order("display_label")
            .execute()
        ).data or []
        return cats
    except Exception as e:
        logger.error("Error categorías catálogo tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener categorías") from e
