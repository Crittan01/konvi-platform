"""
Router de Marketplace — Gestión de publicaciones en Mercado Libre.

Supabase es la fuente de verdad de inventario.
MeLi es un canal de venta cuyo stock refleja Supabase automáticamente.

Endpoints:
  GET    /api/v1/marketplace/listings          — items reales de MeLi + estado de vinculación
  POST   /api/v1/marketplace/link              — vincular item MeLi existente a variante Supabase
  POST   /api/v1/marketplace/import            — importar item MeLi: crea producto en Supabase y vincula
  DELETE /api/v1/marketplace/link/{listing_id} — desvincular (el item MeLi queda intacto)
  PATCH  /api/v1/marketplace/{listing_id}/status   — pausar / activar en MeLi
  PATCH  /api/v1/marketplace/{listing_id}/sync-stock — forzar sync de stock Supabase → MeLi

Flujo de sync automático (llamado desde orders.py y products.py):
  sync_meli_stock(variation_id, new_qty, supabase) → si hay listing activo → PUT MeLi
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from dependencies.auth import _get_service_client, get_current_tenant, require_write_role
from integrations.meli_client import (
    get_item,
    get_items_details,
    get_tenant_meli_credentials,
    get_user_items,
    get_valid_token,
    update_item_listing,
    update_item_quantity,
    update_item_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketplace", tags=["Marketplace"])


# ─── Sync utility (llamado desde otros routers) ───────────────────────────────

async def sync_meli_stock(variation_id: str, new_qty: int, supabase) -> None:
    """
    Empuja stock + precio + precio tachado de una variante a MeLi si tiene listing activo.

    Falla silenciosa: un error en MeLi no debe romper la operación principal.
    Items con status 'closed' en MeLi son ignorados (estado final — PUT rechazado por API).
    """
    try:
        # Resolución: sync_meli_stock recibe variation_id (sin tenant en firma);
        # el tenant se DESCUBRE de la fila listing. variation_id es UUID PK propio.
        listing_res = (
            supabase.table("marketplace_listings")  # tenant_filter:exempt:resolution_lookup_by_variation_id
            .select("id, external_id, tenant_id, meli_variation_id")
            .eq("variation_id", variation_id)
            .eq("provider", "mercadolibre")
            .eq("status", "active")
            .execute()
        )
        if not listing_res.data:
            return

        listing     = listing_res.data[0]
        tenant_id   = listing["tenant_id"]
        external_id = listing["external_id"]
        listing_id  = listing["id"]
        meli_variation_id = listing.get("meli_variation_id")  # bigint o None

        # Leer precio actual de la variante
        var_res = (
            supabase.table("product_variations")
            .select("price, compare_at_price")
            .eq("id", variation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        price          = float(var_res.data["price"])          if var_res.data else None
        original_price = float(var_res.data["compare_at_price"]) if var_res.data and var_res.data.get("compare_at_price") else None

        access_token = await get_valid_token(supabase, tenant_id)
        if not access_token:
            logger.warning("MeLi no conectado para tenant %s — sync omitido", tenant_id)
            return

        # Verificar status real en MeLi antes de mutar
        # MeLi rechaza PUT sobre items 'closed' con 400 Bad Request
        # También leemos variaciones para evitar 400 en items con variaciones MeLi
        try:
            meli_item = await get_item(external_id, access_token)
            meli_status = meli_item.get("status")
            meli_variations = meli_item.get("variations") or []
            if meli_status == "closed":
                logger.warning(
                    "MeLi sync omitido: item %s está 'closed' (estado final). "
                    "Desvincular listing %s para evitar errores recurrentes.",
                    external_id, listing_id
                )
                # Marcar listing local como cerrado para no intentar sync futuro
                supabase.table("marketplace_listings").update(
                    {"status": "closed"}
                ).eq("tenant_id", tenant_id).eq("id", listing_id).execute()
                return
        except Exception as check_err:
            logger.warning("No se pudo verificar status MeLi para %s: %s — intentando sync igual", external_id, check_err)
            meli_variations = []

        if price is not None:
            # Construir payload de variaciones para el PUT:
            # - Si hay meli_variation_id mapeado → stock exactamente a esa variación
            # - Si no → usar variaciones del GET (fallback: primera variación)
            variations_for_put: list | None = None
            if meli_variations:
                if meli_variation_id:
                    variations_for_put = [
                        {"id": v["id"], "available_quantity": new_qty if v["id"] == meli_variation_id else 0}
                        for v in meli_variations if v.get("id")
                    ]
                else:
                    variations_for_put = [{"id": v["id"]} for v in meli_variations if v.get("id")]

            await update_item_listing(external_id, new_qty, price, original_price, access_token, variations_for_put)
        else:
            await update_item_quantity(external_id, new_qty, access_token)

        # Actualizar campos pull desde el GET que ya hicimos (meli_item está disponible)
        try:
            supabase.table("marketplace_listings").update({
                "synced_at":       datetime.now(timezone.utc).isoformat(),
                "status":          meli_status,
                "meli_title":      meli_item.get("title"),
                "meli_thumbnail":  meli_item.get("thumbnail"),
                "meli_condition":  meli_item.get("condition"),
                "meli_category_id": meli_item.get("category_id"),
                "meli_attributes": meli_item.get("attributes"),
            }).eq("tenant_id", tenant_id).eq("id", listing_id).execute()
        except Exception as pull_err:
            logger.warning("No se pudo actualizar pull fields listing %s: %s", listing_id, pull_err)

        logger.info("MeLi sync: item %s → %d u. / $%.0f (variation %s, meli_var %s)",
                    external_id, new_qty, price or 0, variation_id, meli_variation_id)

    except Exception as e:
        logger.error("Error en sync_meli_stock para variation %s: %s", variation_id, e)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/listings")
async def get_listings(tenant_id: str = Depends(get_current_tenant)):
    """
    Retorna los items reales de la cuenta MeLi del tenant más su estado de vinculación.

    Si MeLi no está conectado, retorna lista vacía con connected=False.
    Los datos de stock y precio vienen de MeLi; la vinculación con Supabase
    se indica via variation_id si existe en marketplace_listings.
    """
    supabase = _get_service_client()

    # Verificar conexión MeLi
    creds = get_tenant_meli_credentials(supabase, tenant_id)
    if not creds or not creds.get("user_id"):
        return {"connected": False, "items": [], "paging": {"total": 0}}

    access_token = await get_valid_token(supabase, tenant_id)
    if not access_token:
        return {"connected": False, "items": [], "paging": {"total": 0}}

    user_id = str(creds["user_id"])

    try:
        # 1. Obtener IDs de items del seller (paginado — traemos hasta 100)
        search_res = await get_user_items(user_id, access_token, limit=100, offset=0)
        item_ids = search_res.get("results", [])
        paging = search_res.get("paging", {"total": 0, "limit": 100, "offset": 0})

        if not item_ids:
            return {"connected": True, "items": [], "paging": paging}

        # 2. Detalle de items via multiget
        raw_items = await get_items_details(item_ids, access_token)

        # 3. Cargar vinculaciones existentes en Supabase
        link_res = (
            supabase.table("marketplace_listings")
            .select("id, external_id, variation_id, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .execute()
        )
        links_by_external = {
            lnk["external_id"]: lnk for lnk in (link_res.data or [])
        }

        # 4. Cargar nombres de variantes vinculadas para enriquecer la respuesta
        linked_variation_ids = [
            lnk["variation_id"] for lnk in (link_res.data or []) if lnk.get("variation_id")
        ]
        variation_names = {}
        if linked_variation_ids:
            var_res = (
                supabase.table("product_variations")
                .select("id, sku, stock_quantity, products(title)")
                .eq("tenant_id", tenant_id)
                .in_("id", linked_variation_ids)
                .execute()
            )
            for v in (var_res.data or []):
                product_name = v.get("products", {}).get("title", "") if v.get("products") else ""
                variation_names[v["id"]] = {
                    "sku": v["sku"],
                    "product_name": product_name,
                    "supabase_stock": v["stock_quantity"],
                }

        # 5. Construir respuesta normalizada
        items = []
        for entry in raw_items:
            if entry.get("code") != 200:
                continue
            item = entry.get("body", {})
            if not item:
                continue

            meli_id = item.get("id")
            link = links_by_external.get(meli_id)
            variation_id = link["variation_id"] if link else None
            var_info = variation_names.get(variation_id, {}) if variation_id else {}

            # Variaciones MeLi del item (para selector en UI al vincular)
            raw_variations = item.get("variations") or []
            meli_variations = [
                {
                    "id": v.get("id"),
                    "attributes": v.get("attribute_combinations") or [],
                    "available_quantity": v.get("available_quantity", 0),
                }
                for v in raw_variations if v.get("id")
            ]

            items.append({
                "meli_id": meli_id,
                "title": item.get("title"),
                "status": item.get("status"),         # active | paused | closed
                "price": item.get("price"),
                "available_quantity": item.get("available_quantity"),
                "thumbnail": item.get("thumbnail"),
                "permalink": item.get("permalink"),
                # Variaciones del item en MeLi (lista vacía si item simple)
                "meli_variations": meli_variations,
                # Vinculación con Supabase
                "listing_id": link["id"] if link else None,
                "variation_id": variation_id,
                "meli_variation_id": link.get("meli_variation_id") if link else None,
                "sku": var_info.get("sku"),
                "product_name": var_info.get("product_name"),
                "supabase_stock": var_info.get("supabase_stock"),
                "is_linked": link is not None,
            })

        return {"connected": True, "items": items, "paging": paging}

    except Exception as e:
        logger.error("Error obteniendo listings MeLi tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=502, detail=f"Error al consultar Mercado Libre: {str(e)}")


@router.post("/link")
async def link_listing(
    payload: dict = Body(...),
    tenant_id: str = Depends(get_current_tenant),
    _role: str = Depends(require_write_role),  # A7: gestión de canal = owner/manager
):
    """
    Vincula un item existente de MeLi con una variante de Supabase.

    Body:
      meli_id:           "MCO123456"  (requerido)
      variation_id:      "uuid"        (requerido — variante Supabase)
      meli_price:        15000         (opcional)
      meli_variation_id: 12345678      (opcional — ID de variación MeLi cuando el item tiene variaciones propias)

    Si meli_variation_id está presente, el sync de stock apunta exactamente a esa variación.
    Si no, el sync usa available_quantity a nivel item (item sin variaciones) o la primera variación (fallback).
    """
    supabase = _get_service_client()

    meli_id           = payload.get("meli_id", "").strip().upper()
    variation_id      = payload.get("variation_id")
    meli_price        = payload.get("meli_price")
    meli_variation_id = payload.get("meli_variation_id")  # bigint — variación MeLi específica (opcional)

    if not meli_id or not variation_id:
        raise HTTPException(status_code=400, detail="meli_id y variation_id son requeridos")

    # Verificar que la variante pertenece al tenant
    var_check = (
        supabase.table("product_variations")
        .select("id, stock_quantity")
        .eq("id", variation_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not var_check.data:
        raise HTTPException(status_code=404, detail="Variante no encontrada en Supabase")

    # Verificar conexión MeLi
    access_token = await get_valid_token(supabase, tenant_id)
    if not access_token:
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado para este tenant")

    # Construir URL del item
    external_url = f"https://articulo.mercadolibre.com/{meli_id}"

    try:
        insert_data = {
            "tenant_id":    tenant_id,
            "variation_id": variation_id,
            "external_id":  meli_id,
            "provider":     "mercadolibre",
            "status":       "active",
            "external_price": meli_price,
            "external_url": external_url,
        }
        if meli_variation_id is not None:
            insert_data["meli_variation_id"] = int(meli_variation_id)

        res = supabase.table("marketplace_listings").insert(insert_data).execute()  # tenant_filter:exempt:payload_includes_tenant_id

        # Enriquecer inmediatamente con datos pull desde MeLi
        if res.data:
            listing_id = res.data[0]["id"]
            try:
                item_details = await get_item(meli_id, access_token)
                supabase.table("marketplace_listings").update({
                    "meli_title":      item_details.get("title"),
                    "meli_thumbnail":  item_details.get("thumbnail"),
                    "meli_condition":  item_details.get("condition"),
                    "meli_category_id": item_details.get("category_id"),
                    "meli_attributes": item_details.get("attributes"),
                    "status":          item_details.get("status", "active"),
                    "external_price":  item_details.get("price") or meli_price,
                    "synced_at":       datetime.now(timezone.utc).isoformat(),
                }).eq("tenant_id", tenant_id).eq("id", listing_id).execute()
            except Exception as enrich_err:
                logger.warning("No se pudo enriquecer listing MeLi %s al vincular: %s", meli_id, enrich_err)

        return res.data[0] if res.data else {"ok": True}

    except Exception as e:
        error_str = str(e)
        if "unique" in error_str.lower() or "duplicate" in error_str.lower():
            raise HTTPException(status_code=409, detail="Este item MeLi o esta variante ya están vinculados")
        logger.error("Error vinculando listing MeLi tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear vinculación")


@router.delete("/link/{listing_id}")
async def unlink_listing(
    listing_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _role: str = Depends(require_write_role),  # A7: gestión de canal = owner/manager
):
    """
    Desvincula un item MeLi de su variante Supabase.
    El item en MeLi queda intacto — solo se elimina la sincronización de stock.
    """
    supabase = _get_service_client()

    res = (
        supabase.table("marketplace_listings")
        .delete()
        .eq("id", listing_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Vinculación no encontrada")

    return {"ok": True}


@router.patch("/{listing_id}/status")
async def update_listing_status(
    listing_id: str,
    payload: dict = Body(...),
    tenant_id: str = Depends(get_current_tenant),
    _role: str = Depends(require_write_role),  # A7: gestión de canal = owner/manager
):
    """
    Pausa o activa un listing en MeLi.
    Body: { "status": "active" | "paused" }

    Nota: "closed" es irreversible en MeLi — no se expone desde esta UI.
    """
    supabase = _get_service_client()
    new_status = payload.get("status")

    if new_status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail="Status válido: active | paused")

    # Obtener el listing con external_id
    listing_res = (
        supabase.table("marketplace_listings")
        .select("id, external_id")
        .eq("id", listing_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not listing_res.data:
        raise HTTPException(status_code=404, detail="Listing no encontrado")

    external_id = listing_res.data["external_id"]

    access_token = await get_valid_token(supabase, tenant_id)
    if not access_token:
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado")

    try:
        # 1. Actualizar en MeLi
        await update_item_status(external_id, new_status, access_token)

        # 2. Actualizar estado local
        res = (
            supabase.table("marketplace_listings")
            .update({"status": new_status})
            .eq("id", listing_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        return res.data[0] if res.data else {"ok": True}

    except Exception as e:
        logger.error("Error actualizando status MeLi item %s: %s", external_id, e)
        raise HTTPException(status_code=502, detail=f"Error al actualizar Mercado Libre: {str(e)}")


@router.patch("/{listing_id}/sync-stock")
async def sync_stock_from_supabase(
    listing_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _role: str = Depends(require_write_role),  # A7: gestión de canal = owner/manager
):
    """
    Fuerza la sincronización de stock + precio + precio tachado desde Supabase hacia MeLi.
    Útil para alinear manualmente después de un ajuste o cambio de precio.
    """
    supabase = _get_service_client()

    # Obtener listing + variation
    listing_res = (
        supabase.table("marketplace_listings")
        .select("id, external_id, variation_id, meli_variation_id")
        .eq("id", listing_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not listing_res.data:
        raise HTTPException(status_code=404, detail="Listing no encontrado")

    listing = listing_res.data
    variation_id      = listing.get("variation_id")
    external_id       = listing["external_id"]
    meli_variation_id = listing.get("meli_variation_id")  # bigint o None

    if not variation_id:
        raise HTTPException(status_code=400, detail="Este listing no tiene variante de Supabase vinculada")

    # Obtener stock + precio actuales de Supabase
    var_res = (
        supabase.table("product_variations")
        .select("stock_quantity, price, compare_at_price")
        .eq("id", variation_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not var_res.data:
        raise HTTPException(status_code=404, detail="Variante no encontrada")

    current_stock  = var_res.data["stock_quantity"]
    price          = float(var_res.data["price"])
    original_price = float(var_res.data["compare_at_price"]) if var_res.data.get("compare_at_price") else None

    access_token = await get_valid_token(supabase, tenant_id)
    if not access_token:
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado")

    try:
        # GET previo: verificar status + leer variaciones para evitar 400
        try:
            meli_item = await get_item(external_id, access_token)
        except Exception as get_err:
            # Loguear response body real del error GET para diagnóstico
            get_body = getattr(getattr(get_err, "response", None), "text", str(get_err))
            logger.error("Error GET /items/%s: %s | response: %s", external_id, get_err, get_body)
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo leer el item de Mercado Libre: {get_body}"
            )

        meli_status = meli_item.get("status")
        logger.info("MeLi item %s status=%s buying_mode=%s variations_count=%d",
                    external_id, meli_status, meli_item.get("buying_mode"), len(meli_item.get("variations") or []))

        if meli_status == "closed":
            supabase.table("marketplace_listings").update(
                {"status": "closed"}
            ).eq("id", listing_id).eq("tenant_id", tenant_id).execute()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"La publicación {external_id} está cerrada en Mercado Libre (estado final). "
                    "No es posible modificarla. Crea una nueva publicación en MeLi y vincúlala."
                )
            )

        meli_variations = meli_item.get("variations") or []

        # Construir payload de variaciones con mapping exacto si está disponible
        variations_for_put: list | None = None
        if meli_variations:
            if meli_variation_id:
                variations_for_put = [
                    {"id": v["id"], "available_quantity": current_stock if v["id"] == meli_variation_id else 0}
                    for v in meli_variations if v.get("id")
                ]
            else:
                variations_for_put = [{"id": v["id"]} for v in meli_variations if v.get("id")]

        try:
            await update_item_listing(external_id, current_stock, price, original_price, access_token, variations_for_put)
        except Exception as put_err:
            # Loguear response body real del error PUT para diagnóstico exacto
            put_body = getattr(getattr(put_err, "response", None), "text", str(put_err))
            logger.error("Error PUT /items/%s: %s | response: %s", external_id, put_err, put_body)
            raise HTTPException(
                status_code=502,
                detail=f"MeLi rechazó la actualización: {put_body}"
            )

        return {
            "ok": True,
            "meli_id": external_id,
            "synced_quantity": current_stock,
            "synced_price": price,
            "synced_original_price": original_price,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error inesperado sync MeLi item %s: %s", external_id, e)
        raise HTTPException(status_code=502, detail=f"Error al sincronizar con Mercado Libre: {str(e)}")


@router.post("/import")
async def import_from_meli(
    payload: dict = Body(...),
    tenant_id: str = Depends(get_current_tenant),
    _role: str = Depends(require_write_role),  # A7: gestión de canal = owner/manager
):
    """
    Importa una publicación de MeLi al catálogo interno de Supabase y la vincula.

    Flujo en un solo click:
      1. GET /items/{meli_id}           → trae título, precio, stock de MeLi
      2. INSERT products                → crea producto en Supabase
      3. INSERT product_variations      → crea variante con stock y precio de MeLi
      4. INSERT marketplace_listings    → vincula automáticamente

    Body: { meli_id: "MLA123456", category_id: "uuid" (opcional, categoría OPERATIVA product_categories) }

    Solo importa: título, precio, stock disponible.
    Descripción, imágenes y atributos adicionales se completan desde el Catálogo.
    """
    supabase = _get_service_client()

    meli_id = payload.get("meli_id", "").strip().upper()
    # Coherencia (ADR-0029 D2): el producto importado hereda una categoría OPERATIVA (product_categories,
    # la que usa el bot y el listado), NO la de marketplace. platform_category_id nace null como en toda alta.
    category_id = payload.get("category_id")  # product_categories.id (operativa) — opcional

    if not meli_id:
        raise HTTPException(status_code=400, detail="meli_id es requerido")

    # Verificar credenciales MeLi
    access_token = await get_valid_token(supabase, tenant_id)
    if not access_token:
        raise HTTPException(status_code=400, detail="Mercado Libre no está conectado")

    # Verificar que no exista ya un listing para este meli_id
    existing = (
        supabase.table("marketplace_listings")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("external_id", meli_id)
        .eq("provider", "mercadolibre")
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="Esta publicación ya está vinculada al catálogo")

    # 1. Obtener datos del item desde MeLi
    try:
        meli_item = await get_item(meli_id, access_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo obtener el item de Mercado Libre: {str(e)}")

    title             = meli_item.get("title", meli_id)
    price             = float(meli_item.get("price") or 0)
    available_qty     = int(meli_item.get("available_quantity") or 0)
    permalink         = meli_item.get("permalink")
    # Precio tachado (precio normal antes del descuento en MeLi)
    original_price    = meli_item.get("original_price")
    compare_at_price  = float(original_price) if original_price else None
    # Imagen de portada — primera foto en alta resolución
    pictures          = meli_item.get("pictures") or []
    cover_image_url   = pictures[0].get("secure_url") if pictures else meli_item.get("thumbnail")

    # Generar SKU base desde el ID de MeLi
    sku = f"ML-{meli_id}"

    # Validar ownership de la categoría OPERATIVA (integridad multi-tenant, patrón _assert_category_owned).
    if category_id:
        owned = (
            supabase.table("product_categories")
            .select("id")
            .eq("id", category_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not owned.data:
            raise HTTPException(status_code=422, detail="Categoría de catálogo inválida para este tenant")

    # 2. Crear producto en Supabase (category_id = operativa; platform_category_id nace null — se deriva por categoría).
    prod_payload = {
        "tenant_id":   tenant_id,
        "title":       title,
        "description": f"Importado desde Mercado Libre. ID: {meli_id}",
        "status":      "active",
        "category_id": category_id,
    }
    if cover_image_url:
        prod_payload["cover_image_url"] = cover_image_url

    prod_res = supabase.table("products").insert(prod_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id

    if not prod_res.data:
        raise HTTPException(status_code=500, detail="Error al crear producto en catálogo")

    product_id = prod_res.data[0]["id"]

    # 3. Crear variante con stock y precio de MeLi
    var_payload = {
        "product_id":     product_id,
        "tenant_id":      tenant_id,
        "sku":            sku,
        "price":          price,
        "stock_quantity": available_qty,
        "attributes":     {"default": "Standard"},
    }
    if compare_at_price and compare_at_price > price:
        var_payload["compare_at_price"] = compare_at_price

    try:
        var_res = supabase.table("product_variations").insert(var_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    except Exception as e:
        # Rollback producto creado (A6.2.7: tenant filter defensa cross-tenant)
        supabase.table("products").delete().eq("id", product_id).eq("tenant_id", tenant_id).execute()
        err_str = str(e)
        if "duplicate key" in err_str or "23505" in err_str:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una variante con el SKU {sku} en este catálogo. La publicación ya fue importada previamente."
            )
        logger.error("Error creando variante para import MeLi %s: %s", meli_id, e)
        raise HTTPException(status_code=500, detail="Error al crear variante en catálogo")

    if not var_res.data:
        # Rollback: eliminar el producto creado (A6.2.7: tenant filter)
        supabase.table("products").delete().eq("id", product_id).eq("tenant_id", tenant_id).execute()
        raise HTTPException(status_code=500, detail="Error al crear variante en catálogo")

    variation_id = var_res.data[0]["id"]

    # 4. Crear vínculo en marketplace_listings (con pull fields incluidos)
    link_res = supabase.table("marketplace_listings").insert({
        "tenant_id":       tenant_id,
        "variation_id":    variation_id,
        "external_id":     meli_id,
        "provider":        "mercadolibre",
        "status":          meli_item.get("status", "active"),
        "external_price":  price,
        "external_url":    permalink,
        "meli_title":      title,
        "meli_thumbnail":  meli_item.get("thumbnail"),
        "meli_condition":  meli_item.get("condition"),
        "meli_category_id": meli_item.get("category_id"),
        "meli_attributes": meli_item.get("attributes"),
        "synced_at":       datetime.now(timezone.utc).isoformat(),
    }).execute()

    if not link_res.data:
        # Rollback: eliminar producto y variante (A6.2.7: tenant filter)
        supabase.table("product_variations").delete().eq("id", variation_id).eq("tenant_id", tenant_id).execute()
        supabase.table("products").delete().eq("id", product_id).eq("tenant_id", tenant_id).execute()
        raise HTTPException(status_code=500, detail="Error al vincular con Mercado Libre")

    return {
        "ok":           True,
        "product_id":   product_id,
        "variation_id": variation_id,
        "listing_id":   link_res.data[0]["id"],
        "imported": {
            "title":            title,
            "sku":              sku,
            "price":            price,
            "compare_at_price": compare_at_price,
            "stock_quantity":   available_qty,
            "cover_image_url":  cover_image_url,
            "meli_id":          meli_id,
        }
    }
