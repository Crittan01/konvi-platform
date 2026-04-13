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
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from dependencies.auth import _get_service_client
from integrations import meli_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MeLi Webhook"])

MELI_API_URL = "https://api.mercadolibre.com"

# Mapeo de status MeLi → status interno
MELI_ORDER_STATUS_MAP: dict[str, str] = {
    "confirmed":           "confirmed",
    "payment_required":    "pending",
    "payment_in_process":  "pending",
    "partially_paid":      "pending",
    "paid":                "confirmed",
    "cancelled":           "cancelled",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_valid_token(tenant_id: str, supabase) -> str | None:
    """
    Retorna el access_token vigente del tenant.
    Si está próximo a expirar (< 1 hora), lo renueva automáticamente.
    """
    result = (
        supabase.table("tenant_integrations")
        .select("credentials, meta")
        .eq("tenant_id", tenant_id)
        .eq("provider", "mercadolibre")
        .eq("status", "connected")
        .single()
        .execute()
    )
    if not result.data:
        return None

    creds = result.data.get("credentials", {})
    access_token  = creds.get("access_token")
    refresh_tok   = creds.get("refresh_token")
    expires_in    = creds.get("expires_in", 21600)  # MeLi: 6h por defecto

    # Si no hay refresh_token no podemos renovar — retornar lo que hay
    if not access_token:
        return None

    # Intentar renovar si quedan menos de 3600s (estimación conservadora)
    # En ausencia de expires_at explícito, intentamos y guardamos el nuevo token
    if refresh_tok:
        try:
            token_data = await meli_client.refresh_token(refresh_tok)
            new_access  = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token", refresh_tok)
            new_expires = token_data.get("expires_in", expires_in)

            supabase.table("tenant_integrations").update({
                "credentials": {
                    "access_token":  new_access,
                    "refresh_token": new_refresh,
                    "expires_in":    new_expires,
                },
            }).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()

            logger.info("Token MeLi renovado para tenant %s", tenant_id)
            return new_access
        except Exception as e:
            logger.warning("No se pudo renovar token MeLi tenant %s: %s — usando token existente", tenant_id, e)

    return access_token


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

async def _process_order(resource: str, tenant_id: str, access_token: str, supabase):
    """Crea o actualiza un pedido MeLi en nuestra tabla orders."""
    order_data = await _fetch_meli_resource(resource, access_token)
    if not order_data:
        return

    meli_order_id  = str(order_data.get("id", ""))
    meli_status    = order_data.get("status", "")
    internal_status = MELI_ORDER_STATUS_MAP.get(meli_status, "pending")
    total_amount   = float(order_data.get("total_amount", 0))
    buyer          = order_data.get("buyer", {})
    buyer_name     = f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
    buyer_nickname = buyer.get("nickname", "")
    notes          = f"MeLi order #{meli_order_id} · vendedor: {buyer_nickname or buyer_name}"

    # Buscar si ya existe la orden por external_reference (usamos meli_order_id en notes)
    existing = (
        supabase.table("orders")
        .select("id, status")
        .eq("tenant_id", tenant_id)
        .eq("notes", notes)
        .maybe_single()
        .execute()
    )

    if existing.data:
        # Actualizar estado si cambió
        if existing.data["status"] != internal_status:
            supabase.table("orders").update({
                "status": internal_status,
            }).eq("id", existing.data["id"]).execute()
            logger.info("Orden MeLi %s → status %s (tenant %s)", meli_order_id, internal_status, tenant_id)
    else:
        # Crear orden nueva
        order_result = supabase.table("orders").insert({
            "tenant_id":    tenant_id,
            "status":       internal_status,
            "total_amount": total_amount,
            "notes":        notes,
        }).execute()

        if order_result.data:
            new_order_id = order_result.data[0]["id"]
            # Crear order_items
            meli_items = order_data.get("order_items", [])
            items_to_insert = []
            for item in meli_items:
                items_to_insert.append({
                    "order_id":   new_order_id,
                    "tenant_id":  tenant_id,
                    "title":      item.get("item", {}).get("title", "Producto MeLi"),
                    "quantity":   item.get("quantity", 1),
                    "unit_price": float(item.get("unit_price", 0)),
                })
            if items_to_insert:
                supabase.table("order_items").insert(items_to_insert).execute()

            logger.info("Orden MeLi %s creada → id %s (tenant %s)", meli_order_id, new_order_id, tenant_id)


async def _process_notification(topic: str, resource: str, meli_user_id: str):
    """Procesamiento asíncrono de la notificación MeLi."""
    supabase = _get_service_client()

    tenant_id = await _find_tenant_by_meli_user(meli_user_id, supabase)
    if not tenant_id:
        logger.warning("No se encontró tenant para meli_user_id=%s", meli_user_id)
        return

    access_token = await _get_valid_token(tenant_id, supabase)
    if not access_token:
        logger.error("No hay token MeLi válido para tenant %s", tenant_id)
        return

    if topic == "orders_v2":
        await _process_order(resource, tenant_id, access_token, supabase)
    elif topic == "items":
        # Fetch the item from MeLi
        item_data = await _fetch_meli_resource(resource, access_token)
        if item_data:
            meli_status = item_data.get("status", "active")
            # Update our database sync status
            supabase.table("marketplace_listings").update({
                "status": meli_status,
                "external_price": item_data.get("price")
            }).eq("tenant_id", tenant_id).eq("external_id", item_data.get("id")).execute()
            logger.info("Sync Webhook: Artículo MeLi %s actualizado a status %s para tenant %s", item_data.get("id"), meli_status, tenant_id)
    elif topic == "shipments":
        logger.info("Notificación shipments MeLi recibida — sync de envíos pendiente (Fase 12)")
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
        # MeLi a veces envía pings vacíos — responder 200 siempre
        return JSONResponse({"ok": True})

    topic       = body.get("topic", "")
    resource    = body.get("resource", "")
    meli_user_id = str(body.get("user_id", ""))

    logger.info("Webhook MeLi recibido — topic=%s resource=%s user_id=%s", topic, resource, meli_user_id)

    if topic and resource and meli_user_id:
        background_tasks.add_task(_process_notification, topic, resource, meli_user_id)

    # Siempre 200 — MeLi no acepta demoras
    return JSONResponse({"ok": True})
