import uuid
from fastapi import APIRouter, Depends, HTTPException, Body
from dependencies.auth import get_current_user_tenant, _get_service_client

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

@router.get("/listings")
async def get_listings(tenant: dict = Depends(get_current_user_tenant)):
    """
    Devuelve todo el catálogo (variaciones) cruzado con su posible estado 
    en marketplace_listings (Mercado Libre).
    """
    supabase = _get_service_client()
    tenant_id = tenant["tenant_id"]

    # Traemos las variaciones con información de producto
    var_res = supabase.table("product_variations").select(
        "id, product_id, sku, price, stock_quantity, products(name)"
    ).eq("tenant_id", tenant_id).execute()

    if not var_res.data:
        return {"items": []}

    variations = var_res.data

    # Traemos los listings activos de ese tenant
    list_res = supabase.table("marketplace_listings").select(
        "id, variation_id, external_id, status, external_price, external_url"
    ).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()

    listings = {item["variation_id"]: item for item in (list_res.data or [])}

    results = []
    for var in variations:
        product_name = var.get("products", {}).get("name", "Unknown") if var.get("products") else "Unknown"
        listing = listings.get(var["id"])

        results.append({
            "variation_id": var["id"],
            "product_name": product_name,
            "sku": var["sku"],
            "base_price": var["price"],
            "stock": var["stock_quantity"],
            "is_published": listing is not None,
            "listing_id": listing["id"] if listing else None,
            "external_id": listing["external_id"] if listing else None,
            "status": listing["status"] if listing else "unlisted",
            "external_price": listing["external_price"] if listing else var["price"],
            "external_url": listing["external_url"] if listing else None,
        })

    return {"items": results}


@router.post("/publish")
async def publish_listing(
    payload: dict = Body(...),
    tenant: dict = Depends(get_current_user_tenant)
):
    """
    Publica una variación en Mercado Libre.
    (MOCK: Genera un ID 'MLA...' para validar la arquitectura funcional)
    """
    supabase = _get_service_client()
    tenant_id = tenant["tenant_id"]
    variation_id = payload.get("variation_id")
    external_price = payload.get("external_price")

    if not variation_id or not external_price:
        raise HTTPException(status_code=400, detail="Missing variation_id or external_price")

    # 1. Chequear si la variación existe
    var_chk = supabase.table("product_variations").select("id").eq("id", variation_id).eq("tenant_id", tenant_id).single().execute()
    if not var_chk.data:
        raise HTTPException(status_code=404, detail="Variation not found")

    # 2. MOCK: Aquí se llamaría a httpx.post("https://api.mercadolibre.com/items", ...)
    # Para la demo, simularemos el comportamiento existoso de Mercado Libre:
    fake_mla_id = f"MLA{uuid.uuid4().hex[:10].upper()}"

    # 3. Guardar en Base de Datos de Sindicación
    res = supabase.table("marketplace_listings").insert({
        "tenant_id": tenant_id,
        "variation_id": variation_id,
        "external_id": fake_mla_id,
        "provider": "mercadolibre",
        "status": "active",
        "external_price": external_price,
        "external_url": f"https://articulo.mercadolibre.com.ar/{fake_mla_id}"
    }).execute()

    return res.data[0] if res.data else {"ok": True}


@router.patch("/{listing_id}/status")
async def update_listing_status(
    listing_id: str,
    payload: dict = Body(...),
    tenant: dict = Depends(get_current_user_tenant)
):
    """
    Pausa o Activa una publicación.
    """
    supabase = _get_service_client()
    tenant_id = tenant["tenant_id"]
    new_status = payload.get("status")

    if new_status not in ["active", "paused", "closed"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # MOCK: Aquí notificaríamos a la API externa PUT /items/{external_id} {"status": "paused"}

    res = supabase.table("marketplace_listings").update({
        "status": new_status
    }).eq("id", listing_id).eq("tenant_id", tenant_id).execute()

    return res.data[0] if res.data else {"ok": True}
