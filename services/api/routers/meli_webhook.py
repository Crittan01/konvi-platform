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

Defensa de origen:
  MeLi NO firma webhooks. La doc oficial publica las IPs desde donde envía
  notificaciones: si la IP del request no está en esa lista, rechazamos
  con 403 antes de hacer cualquier trabajo. Esto cierra el vector DoS y
  el de costo (sin filtro, un atacante podría disparar GETs a la API MeLi).

Referencia oficial:
  https://developers.mercadolibre.com.co/es_ar/notificaciones
"""
import logging
import os
import asyncio
import httpx
import time
import threading
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from dependencies.auth import _get_service_client, get_service_client
from dependencies.security import webhook_rate_limit_check
from integrations import meli_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MeLi Webhook"])

MELI_API_URL = "https://api.mercadolibre.com"

# IPs oficiales desde donde MeLi envía notificaciones.
# Fuente: https://developers.mercadolibre.com.co/es_ar/notificaciones
# Sección "Historial de notificaciones" (verificada 2026-04-28).
# Si MeLi cambia las IPs, override por env var MELI_WEBHOOK_ALLOWED_IPS (CSV).
_MELI_DEFAULT_NOTIFICATION_IPS: frozenset[str] = frozenset({
    "54.88.218.97",
    "18.215.140.160",
    "18.213.114.129",
    "18.206.34.84",
})


def _load_allowed_meli_ips() -> frozenset[str]:
    raw = os.getenv("MELI_WEBHOOK_ALLOWED_IPS", "").strip()
    if not raw:
        return _MELI_DEFAULT_NOTIFICATION_IPS
    ips = {ip.strip() for ip in raw.split(",") if ip.strip()}
    return frozenset(ips) if ips else _MELI_DEFAULT_NOTIFICATION_IPS


_ALLOWED_MELI_IPS: frozenset[str] = _load_allowed_meli_ips()

# Idempotencia in-memory para webhooks repetidos.
# MeLi reintenta hasta 8 veces durante 1 hora si no recibe 200; un atacante
# con IP legítima podría replay. Memoización TTL=300s evita reprocesar el
# mismo (application_id, resource, sent). Por instancia (no distribuido):
# acepta replay cross-instancia, pero el handler interno ya es idempotente.
_DEDUP_TTL_SECONDS = 300
_dedup_lock = threading.Lock()
_dedup_seen: dict[str, float] = {}


def _is_duplicate_event(application_id: str, resource: str, sent: str) -> bool:
    if not (application_id and resource and sent):
        return False
    key = f"{application_id}|{resource}|{sent}"
    now = time.time()
    with _dedup_lock:
        cutoff = now - _DEDUP_TTL_SECONDS
        # Limpieza oportunista
        if len(_dedup_seen) > 1000:
            for k, ts in list(_dedup_seen.items()):
                if ts < cutoff:
                    _dedup_seen.pop(k, None)
        last_seen = _dedup_seen.get(key)
        if last_seen and last_seen >= cutoff:
            return True
        _dedup_seen[key] = now
        return False


def _extract_request_ip(request: Request) -> str:
    """Extrae IP real del cliente. Prefiere x-forwarded-for[0] (LB Render)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return ""


def _verify_meli_origin(request: Request, supabase=Depends(get_service_client)) -> None:
    """Dependency: valida origen IP + rate-limit. <1ms en happy path."""
    ip = _extract_request_ip(request)
    if ip not in _ALLOWED_MELI_IPS:
        ua = request.headers.get("user-agent", "")[:80]
        logger.warning("meli_webhook.rejected_origin ip=%s ua=%r", ip or "<empty>", ua)
        raise HTTPException(status_code=403, detail="Origen no autorizado")
    allowed, retry_after = webhook_rate_limit_check(
        supabase, ip=ip, bucket="webhook.meli", limit=200, window_seconds=60,
    )
    if not allowed:
        logger.warning("meli_webhook.rate_limited ip=%s retry_after=%s", ip, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido",
            headers={"Retry-After": str(retry_after)},
        )

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
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            if not var_result.data:
                continue

            new_stock = var_result.data["stock_quantity"] - quantity

            supabase.table("product_variations").update(
                {"stock_quantity": new_stock}
            ).eq("id", variation_id).eq("tenant_id", tenant_id).execute()

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


def _upsert_meli_contact(buyer: dict, tenant_id: str, supabase) -> str | None:
    """
    Crea o actualiza un contacto desde los datos del comprador MeLi.
    Retorna contact_id si hay teléfono disponible; None si no hay datos suficientes.
    MeLi expone phone en billing_info para vendedores verificados.
    """
    phone = (
        (buyer.get("billing_info") or {}).get("phone")
        or buyer.get("phone")
        or None
    )
    if not phone:
        return None

    buyer_name = (
        f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
        or buyer.get("nickname")
        or None
    )
    try:
        result = supabase.table("contacts").upsert(
            {"tenant_id": tenant_id, "phone": str(phone).strip(), "name": buyer_name},
            on_conflict="tenant_id,phone",
        ).execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        logger.warning("No se pudo crear/actualizar contacto MeLi (phone=%s): %s", phone, e)
        return None


async def _process_order(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Crea o actualiza un pedido MeLi en nuestra tabla orders.
    Al crear, vincula variation_id en order_items, crea contacto si hay teléfono
    y decrementa stock si el pedido llega confirmado/pagado desde MeLi.
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
            }).eq("id", existing.data["id"]).eq("tenant_id", tenant_id).execute()
            logger.info("Orden MeLi %s → status %s (tenant %s)", meli_order_id, internal_status, tenant_id)
    else:
        # Crear contacto si hay teléfono disponible
        contact_id = _upsert_meli_contact(buyer, tenant_id, supabase)

        # Resolver variation_id para cada item del pedido
        meli_order_items = order_data.get("order_items", [])
        meli_item_ids    = [item.get("item", {}).get("id", "") for item in meli_order_items if item.get("item", {}).get("id")]
        variation_map    = _resolve_variation_ids(meli_item_ids, tenant_id, supabase)

        order_payload = {
            "tenant_id":    tenant_id,
            "status":       internal_status,
            "total_amount": total_amount,
            "notes":        notes,
        }
        if contact_id:
            order_payload["contact_id"] = contact_id

        order_result = supabase.table("orders").insert(order_payload).execute()

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

            logger.info("Orden MeLi %s creada → id %s, status=%s, contact=%s (tenant %s)",
                        meli_order_id, new_order_id, internal_status, contact_id, tenant_id)


async def _process_shipment(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Actualiza el estado de la orden asociada al envío y persiste el tracking.

    MeLi envía el shipment_id en el recurso. El shipment contiene order_id,
    que usamos para buscar la orden en Supabase por su campo notes.

    Solo avanza el estado — nunca retrocede (shipped no vuelve a processing).
    El tracking (tracking_number, carrier, estimated_delivery) se persiste en
    order_tracking independientemente del avance de estado de la orden.
    """
    shipment_data = await _fetch_meli_resource(resource, access_token)
    if not shipment_data:
        return

    shipment_id     = str(shipment_data.get("id", ""))
    shipment_status = shipment_data.get("status", "")
    meli_order_id   = str(shipment_data.get("order_id", ""))

    if not meli_order_id:
        logger.info("Shipment MeLi %s sin order_id — sin acción", shipment_id)
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

    order_id = existing.data["id"] if existing.data else None

    # Actualizar estado de la orden si el shipment implica un avance
    new_order_status = MELI_SHIPMENT_ORDER_STATUS_MAP.get(shipment_status)
    if order_id and new_order_status:
        current_status = existing.data["status"]
        STATUS_RANK = {"pending": 0, "confirmed": 1, "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 5}
        if STATUS_RANK.get(new_order_status, 0) > STATUS_RANK.get(current_status, 0):
            supabase.table("orders").update({
                "status": new_order_status,
            }).eq("id", order_id).eq("tenant_id", tenant_id).execute()
            logger.info("Orden MeLi %s → status %s (vía shipment %s, tenant %s)",
                        meli_order_id, new_order_status, shipment_id, tenant_id)
        else:
            logger.info("Shipment MeLi %s: estado %s no avanza sobre %s — omitido",
                        shipment_id, new_order_status, current_status)
    elif not existing.data:
        logger.warning("Shipment MeLi %s: no se encontró orden con notes like '%s%%' (tenant %s)",
                       shipment_id, notes_prefix, tenant_id)

    # Persistir tracking en order_tracking (aunque la orden no haya avanzado de estado)
    if order_id and shipment_id:
        tracking_number = shipment_data.get("tracking_number")
        carrier         = (shipment_data.get("shipping_option") or {}).get("name")
        tracking_url    = shipment_data.get("tracking_url")

        estimated_delivery = None
        est_final = shipment_data.get("estimated_delivery_final") or {}
        if est_final.get("date"):
            try:
                estimated_delivery = str(est_final["date"])[:10]   # YYYY-MM-DD
            except Exception:
                pass

        try:
            existing_tracking = (
                supabase.table("order_tracking")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("provider", "mercadolibre")
                .eq("external_id", shipment_id)
                .maybe_single()
                .execute()
            )
            tracking_payload = {
                "tenant_id":          tenant_id,
                "order_id":           order_id,
                "provider":           "mercadolibre",
                "external_id":        shipment_id,
                "status":             shipment_status,
                "tracking_number":    tracking_number,
                "tracking_url":       tracking_url,
                "carrier":            carrier,
                "estimated_delivery": estimated_delivery,
                "raw":                shipment_data,
            }
            if existing_tracking.data:
                supabase.table("order_tracking").update(tracking_payload).eq(
                    "id", existing_tracking.data["id"]
                ).execute()
            else:
                supabase.table("order_tracking").insert(tracking_payload).execute()
            logger.info("Tracking MeLi shipment %s → %s (orden %s)", shipment_id, shipment_status, order_id)
        except Exception as track_err:
            logger.warning("No se pudo persistir tracking MeLi shipment %s: %s", shipment_id, track_err)


async def _process_notification(topic: str, resource: str, meli_user_id: str):
    """Procesamiento asíncrono de la notificación MeLi."""
    supabase = _get_service_client()

    tenant_id = await _find_tenant_by_meli_user(meli_user_id, supabase)
    if not tenant_id:
        logger.info("Webhook MeLi ignorado: meli_user_id=%s sin tenant asociado", meli_user_id)
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
                "status":          item_data.get("status", "active"),
                "external_price":  item_data.get("price"),
                "meli_title":      item_data.get("title"),
                "meli_thumbnail":  item_data.get("thumbnail"),
                "meli_condition":  item_data.get("condition"),
                "meli_category_id": item_data.get("category_id"),
                "meli_attributes": item_data.get("attributes"),
                "synced_at":       datetime.now(timezone.utc).isoformat(),
            }).eq("tenant_id", tenant_id).eq("external_id", item_data.get("id")).execute()
            logger.info("Listing MeLi %s → status %s (pull completo, tenant %s)",
                        item_data.get("id"), item_data.get("status"), tenant_id)
    elif topic == "shipments":
        await _process_shipment(resource, tenant_id, access_token, supabase)
    else:
        logger.info("Tópico MeLi no manejado: %s", topic)


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/webhook", dependencies=[Depends(_verify_meli_origin)])
async def meli_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe notificaciones IPN de MeLi.
    Retorna 200 inmediatamente y procesa en background.
    MeLi reintenta hasta 8 veces si no recibe 200 en 500ms.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    topic        = body.get("topic", "")
    resource     = body.get("resource", "")
    meli_user_id = str(body.get("user_id", ""))
    application_id = str(body.get("application_id", ""))
    sent         = str(body.get("sent", ""))

    logger.info("Webhook MeLi — topic=%s resource=%s user_id=%s", topic, resource, meli_user_id)

    if not (topic and resource and meli_user_id):
        return JSONResponse({"ok": True})

    if _is_duplicate_event(application_id, resource, sent):
        logger.info("meli_webhook.duplicate_skipped resource=%s sent=%s", resource, sent)
        return JSONResponse({"ok": True, "duplicate": True})

    background_tasks.add_task(_process_notification, topic, resource, meli_user_id)
    return JSONResponse({"ok": True})
