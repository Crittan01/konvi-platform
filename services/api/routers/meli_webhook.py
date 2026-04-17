"""
Webhook de Mercado Libre (IPN — Instant Payment Notifications).

Tópicos registrados: orders_v2, items, shipments.

Flujo:
  1. MeLi hace POST → respondemos 200 inmediatamente (MeLi penaliza latencia)
  2. BackgroundTask procesa la notificación de forma asíncrona:
     a. Busca el tenant por meli user_id en tenant_integrations.meta
     b. Obtiene el access_token del tenant (con auto-refresh si expiró)
     c. Consulta el recurso en la MeLi API
     d. Persiste en nuestra base de datos

Referencia oficial:
  https://developers.mercadolibre.com/es_ar/recibir-notificaciones
"""
import logging
import asyncio
import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from dependencies.auth import _get_service_client
from integrations import meli_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MeLi Webhook"])

MELI_API_URL = "https://api.mercadolibre.com"

# Mapeo de status MeLi (pedido) → status interno
MELI_ORDER_STATUS_MAP: dict[str, str] = {
    "confirmed":          "confirmed",
    "payment_required":   "pending",
    "payment_in_process": "pending",
    "partially_paid":     "pending",
    "paid":               "confirmed",
    "cancelled":          "cancelled",
}

# Mapeo de status MeLi (envío) → status de orden interno
# Solo se actualiza cuando el shipment avanza — no retrocede.
MELI_SHIPMENT_ORDER_STATUS_MAP: dict[str, str] = {
    "handling":      "processing",
    "ready_to_ship": "processing",
    "shipped":       "shipped",
    "delivered":     "delivered",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _find_tenant_by_meli_user(meli_user_id: str, supabase) -> str | None:
    """Busca el tenant que tiene ese meli user_id en tenant_integrations.meta."""
    result = (
        supabase.table("tenant_integrations")
        .select("tenant_id, meta")
        .eq("provider", "mercadolibre")
        .eq("status", "connected")
        .execute()
    )
    for row in (result.data or []):
        if str(row.get("meta", {}).get("user_id", "")) == str(meli_user_id):
            return row["tenant_id"]
    return None


async def _fetch_meli_resource(resource_path: str, access_token: str) -> dict | None:
    """GET al recurso indicado en la MeLi API."""
    url = f"{MELI_API_URL}{resource_path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code != 200:
            logger.warning("MeLi API %s → %d: %s", url, resp.status_code, resp.text[:200])
            return None
        return resp.json()


# ─── Procesamiento por tópico ────────────────────────────────────────────────

def _resolve_variation_ids(meli_item_ids: list[str], tenant_id: str, supabase) -> dict[str, str]:
    """
    Dado una lista de MeLi item IDs, retorna un mapa {meli_id: variation_id}
    buscando en marketplace_listings las variantes vinculadas del tenant.
    Items sin vínculo no aparecen en el resultado.
    """
    if not meli_item_ids:
        return {}
    try:
        result = (
            supabase.table("marketplace_listings")
            .select("external_id, variation_id")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .in_("external_id", meli_item_ids)
            .execute()
        )
        return {
            row["external_id"]: row["variation_id"]
            for row in (result.data or [])
            if row.get("variation_id")
        }
    except Exception as e:
        logger.warning("Error resolviendo variation_ids para items MeLi: %s", e)
        return {}


def _decrement_stock_for_meli_order(order_id: str, tenant_id: str, supabase) -> None:
    """
    Decrementa stock de las variantes de un pedido MeLi y sincroniza con MeLi.
    Idempotente: si stock_movements ya tiene un registro para esta orden, no repite.
    """
    try:
        # Verificar idempotencia: ya fue procesado si existe un movimiento con este order_id
        already = (
            supabase.table("stock_movements")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id)
            .limit(1)
            .execute()
        )
        if already.data:
            logger.info("Stock ya decrementado para orden MeLi %s — omitido", order_id)
            return

        items_result = (
            supabase.table("order_items")
            .select("variation_id, quantity")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        from routers.marketplace import sync_meli_stock

        for item in (items_result.data or []):
            variation_id = item.get("variation_id")
            quantity     = item.get("quantity", 0)
            if not variation_id or quantity <= 0:
                continue

            var_result = (
                supabase.table("product_variations")
                .select("stock_quantity")
                .eq("id", variation_id)
                .single()
                .execute()
            )
            if not var_result.data:
                continue

            new_stock = var_result.data["stock_quantity"] - quantity

            supabase.table("product_variations").update(
                {"stock_quantity": new_stock}
            ).eq("id", variation_id).execute()

            supabase.table("stock_movements").insert({
                "tenant_id":    tenant_id,
                "variation_id": variation_id,
                "order_id":     order_id,
                "delta":        -quantity,
                "new_stock":    new_stock,
                "reason":       "sale",
            }).execute()

            asyncio.ensure_future(sync_meli_stock(variation_id, new_stock, supabase))
            logger.info("Stock variation %s → %d (orden MeLi %s)", variation_id, new_stock, order_id)

    except Exception as e:
        logger.error("Error decrementando stock para orden MeLi %s: %s", order_id, e)


async def _process_order(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Crea o actualiza un pedido MeLi en nuestra tabla orders.
    Al crear, vincula variation_id en order_items y decrementa stock si el pedido
    ya viene confirmado/pagado desde MeLi.
    """
    order_data = await _fetch_meli_resource(resource, access_token)
    if not order_data:
        return

    meli_order_id   = str(order_data.get("id", ""))
    meli_status     = order_data.get("status", "")
    internal_status = MELI_ORDER_STATUS_MAP.get(meli_status, "pending")
    total_amount    = float(order_data.get("total_amount", 0))
    buyer           = order_data.get("buyer", {})
    buyer_name      = f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
    buyer_nickname  = buyer.get("nickname", "")
    notes           = f"MeLi order #{meli_order_id} · vendedor: {buyer_nickname or buyer_name}"

    existing = (
        supabase.table("orders")
        .select("id, status")
        .eq("tenant_id", tenant_id)
        .eq("notes", notes)
        .maybe_single()
        .execute()
    )

    if existing.data:
        # Actualizar estado si avanzó
        if existing.data["status"] != internal_status:
            supabase.table("orders").update({
                "status": internal_status,
            }).eq("id", existing.data["id"]).execute()
            logger.info("Orden MeLi %s → status %s (tenant %s)", meli_order_id, internal_status, tenant_id)
    else:
        # Resolver variation_id para cada item del pedido
        meli_order_items = order_data.get("order_items", [])
        meli_item_ids    = [item.get("item", {}).get("id", "") for item in meli_order_items if item.get("item", {}).get("id")]
        variation_map    = _resolve_variation_ids(meli_item_ids, tenant_id, supabase)

        order_result = supabase.table("orders").insert({
            "tenant_id":    tenant_id,
            "status":       internal_status,
            "total_amount": total_amount,
            "notes":        notes,
        }).execute()

        if order_result.data:
            new_order_id = order_result.data[0]["id"]

            items_to_insert = [
                {
                    "order_id":     new_order_id,
                    "tenant_id":    tenant_id,
                    "title":        item.get("item", {}).get("title", "Producto MeLi"),
                    "quantity":     item.get("quantity", 1),
                    "unit_price":   float(item.get("unit_price", 0)),
                    "variation_id": variation_map.get(item.get("item", {}).get("id", "")),
                }
                for item in meli_order_items
            ]
            if items_to_insert:
                supabase.table("order_items").insert(items_to_insert).execute()

            # Decrementar stock si el pedido llega ya confirmado/pagado
            if internal_status == "confirmed":
                _decrement_stock_for_meli_order(new_order_id, tenant_id, supabase)

            logger.info("Orden MeLi %s creada → id %s, status=%s (tenant %s)",
                        meli_order_id, new_order_id, internal_status, tenant_id)


async def _process_shipment(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Actualiza el estado de la orden asociada al envío.

    MeLi envía el shipment_id en el recurso. El shipment contiene order_id,
    que usamos para buscar la orden en Supabase por su campo notes.

    Solo avanza el estado — nunca retrocede (shipped no vuelve a processing).
    """
    shipment_data = await _fetch_meli_resource(resource, access_token)
    if not shipment_data:
        return

    shipment_id     = str(shipment_data.get("id", ""))
    shipment_status = shipment_data.get("status", "")
    meli_order_id   = str(shipment_data.get("order_id", ""))

    new_order_status = MELI_SHIPMENT_ORDER_STATUS_MAP.get(shipment_status)
    if not new_order_status or not meli_order_id:
        logger.info("Shipment MeLi %s status=%s — sin acción", shipment_id, shipment_status)
        return

    # Buscar la orden por el MeLi order ID almacenado en notes
    notes_prefix = f"MeLi order #{meli_order_id}"
    existing = (
        supabase.table("orders")
        .select("id, status")
        .eq("tenant_id", tenant_id)
        .like("notes", f"{notes_prefix}%")
        .maybe_single()
        .execute()
    )

    if not existing.data:
        logger.warning("Shipment MeLi %s: no se encontró orden con notes like '%s%%' (tenant %s)",
                       shipment_id, notes_prefix, tenant_id)
        return

    current_status = existing.data["status"]
    order_id       = existing.data["id"]

    # Definir orden de estados para evitar retrocesos
    STATUS_RANK = {"pending": 0, "confirmed": 1, "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 5}
    current_rank = STATUS_RANK.get(current_status, 0)
    new_rank     = STATUS_RANK.get(new_order_status, 0)

    if new_rank <= current_rank:
        logger.info("Shipment MeLi %s: estado %s no avanza sobre %s — omitido",
                    shipment_id, new_order_status, current_status)
        return

    supabase.table("orders").update({
        "status": new_order_status,
    }).eq("id", order_id).execute()

    logger.info("Orden MeLi %s → status %s (vía shipment %s, tenant %s)",
                meli_order_id, new_order_status, shipment_id, tenant_id)


async def _process_notification(topic: str, resource: str, meli_user_id: str):
    """Procesamiento asíncrono de la notificación MeLi."""
    supabase = _get_service_client()

    tenant_id = await _find_tenant_by_meli_user(meli_user_id, supabase)
    if not tenant_id:
        logger.warning("No se encontró tenant para meli_user_id=%s", meli_user_id)
        return

    access_token = await meli_client.get_valid_token(supabase, tenant_id)
    if not access_token:
        logger.error("No hay token MeLi válido para tenant %s", tenant_id)
        return

    if topic == "orders_v2":
        await _process_order(resource, tenant_id, access_token, supabase)
    elif topic == "items":
        item_data = await _fetch_meli_resource(resource, access_token)
        if item_data:
            supabase.table("marketplace_listings").update({
                "status":         item_data.get("status", "active"),
                "external_price": item_data.get("price"),
            }).eq("tenant_id", tenant_id).eq("external_id", item_data.get("id")).execute()
            logger.info("Listing MeLi %s → status %s (tenant %s)",
                        item_data.get("id"), item_data.get("status"), tenant_id)
    elif topic == "shipments":
        await _process_shipment(resource, tenant_id, access_token, supabase)
    else:
        logger.info("Tópico MeLi no manejado: %s", topic)


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def meli_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe notificaciones IPN de MeLi.
    Retorna 200 inmediatamente y procesa en background.
    MeLi reintenta hasta 10 veces si no recibe 200.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    topic        = body.get("topic", "")
    resource     = body.get("resource", "")
    meli_user_id = str(body.get("user_id", ""))

    logger.info("Webhook MeLi — topic=%s resource=%s user_id=%s", topic, resource, meli_user_id)

    if topic and resource and meli_user_id:
        background_tasks.add_task(_process_notification, topic, resource, meli_user_id)

    return JSONResponse({"ok": True})
