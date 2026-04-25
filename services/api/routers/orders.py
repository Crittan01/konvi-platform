"""
Router de Pedidos — CRUD con aislamiento multi-tenant via RLS.

Endpoints:
  GET    /api/v1/orders/                   — listar pedidos del tenant
  POST   /api/v1/orders/                   — crear pedido con ítems   [owner, manager]
  GET    /api/v1/orders/{id}               — detalle con ítems
  PATCH  /api/v1/orders/{id}               — cambiar estado / notas   [owner, manager]
  POST   /api/v1/orders/{id}/payment-link  — generar link de pago Wompi [owner, manager]

Estados válidos: pending | pending_payment → confirmed → processing → shipped → delivered | cancelled
"""
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from dependencies.idempotency import (
    abort_idempotency,
    begin_idempotency,
    finalize_idempotency,
    payload_fingerprint,
)
from dependencies.plans import PLAN_ORDERS_CREATE
from dependencies.security import RL_WRITE_DEFAULT
from routers.marketplace import sync_meli_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])

VALID_STATUSES = {"pending", "pending_payment", "confirmed", "processing", "shipped", "delivered", "cancelled"}

WOMPI_PAYMENT_LINK_TTL_MINUTES = 30  # Reserva de stock expira en 30 min


# ─── Modelos ─────────────────────────────────────────────────────────────────

class OrderItemCreate(BaseModel):
    product_id: Optional[str] = None
    variation_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=180)
    unit_price: float = Field(..., gt=0)
    unit_cost: Optional[float] = None
    quantity: int = Field(default=1, ge=1)


class OrderCreate(BaseModel):
    contact_id: Optional[str] = None
    conversation_id: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1200)
    shipping_cost: float = Field(default=0.0, ge=0.0, le=999999999.0)
    items: List[OrderItemCreate] = Field(..., min_length=1)
    # Si True, el pedido se crea en 'pending' y se confirma de inmediato
    # (usa el mismo flujo de decremento de stock que PATCH status=confirmed).
    # Usado por el flujo de creación desde Inbox (agente humano con contexto completo).
    auto_confirm: bool = Field(default=False)
    # Si True, el pedido se crea en 'pending_payment' (stock reservado, no descontado).
    # El stock se descuenta definitivamente cuando el webhook de Wompi confirma el pago.
    payment_link: bool = Field(default=False)


class OrderPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1200)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_orders(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista pedidos del tenant con datos del contacto. Filtra por status opcional."""
    try:
        if status and status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Status inválido. Valores permitidos: {', '.join(sorted(VALID_STATUSES))}",
            )
        query = (
            supabase.table("orders")
            .select("id, status, total_amount, shipping_cost, notes, created_at, contact_id, contacts(phone, name)")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error("Error listando pedidos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener pedidos")


@router.post("/", response_model=dict, status_code=201)
async def create_order(
    order: OrderCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _plan: object = Depends(PLAN_ORDERS_CREATE),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Crea pedido con ítems. Calcula total automáticamente. Solo owner/manager."""
    idem_session = None
    try:
        request_hash = payload_fingerprint(order.model_dump(mode="json"))
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        total = sum(item.unit_price * item.quantity for item in order.items) + order.shipping_cost

        initial_status = (
            "pending_payment" if order.payment_link else "pending"
        )
        order_result = supabase.table("orders").insert({
            "tenant_id": tenant_id,
            "contact_id": order.contact_id,
            "conversation_id": order.conversation_id,
            "status": initial_status,
            "total_amount": total,
            "shipping_cost": order.shipping_cost,
            "notes": order.notes,
        }).execute()

        if not order_result.data:
            raise HTTPException(status_code=500, detail="Error al crear pedido")

        order_id = order_result.data[0]["id"]

        # Lookup cost_price for the variations since we shouldn't rely on frontend
        variation_ids = [str(item.variation_id) for item in order.items if item.variation_id]
        variation_costs = {}
        if variation_ids:
            var_res = (
                supabase.table("product_variations")
                .select("id, cost_price")
                .eq("tenant_id", tenant_id)
                .in_("id", variation_ids)
                .execute()
            )
            variation_costs = {v["id"]: float(v["cost_price"] or 0) for v in (var_res.data or [])}

        items_data = [
            {
                "order_id": order_id,
                "tenant_id": tenant_id,
                "product_id": item.product_id,
                "variation_id": item.variation_id,
                "title": item.title,
                "unit_price": item.unit_price,
                "unit_cost": variation_costs.get(str(item.variation_id), 0.0) if item.variation_id else 0.0,
                "quantity": item.quantity,
            }
            for item in order.items
        ]
        supabase.table("order_items").insert(items_data).execute()

        response_body = {**order_result.data[0], "items": items_data}

        # Confirmar de inmediato si el frontend lo solicita (Inbox flow)
        if order.auto_confirm:
            try:
                (
                    supabase.table("orders")
                    .update({"status": "confirmed"})
                    .eq("id", order_id)
                    .eq("tenant_id", tenant_id)
                    .execute()
                )
                _decrement_stock_on_confirm(supabase, order_id, tenant_id)
                response_body["status"] = "confirmed"
                logger.info("Pedido %s auto-confirmado desde Inbox (stock decrementado)", order_id)
            except Exception as ce:
                logger.error("Error auto-confirmando pedido %s: %s", order_id, ce)
                # No fallar la creación — el pedido quedó en pending

        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=201,
            body=response_body,
        )
        return response_body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error creando pedido tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear pedido")


@router.get("/{order_id}", response_model=dict)
async def get_order(
    order_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Detalle del pedido con ítems y datos del contacto."""
    try:
        result = (
            supabase.table("orders")
            .select("*, contacts(phone, name), order_items(id, title, unit_price, unit_cost, quantity, product_id, variation_id)")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener pedido")


@router.patch("/{order_id}", response_model=dict)
async def patch_order(
    order_id: str,
    patch: OrderPatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cambia estado y/o notas del pedido. Solo owner/manager.

    Lógica especial:
    - pending → confirmed: decrementa stock de cada variante de los ítems del pedido
      e inserta registros en stock_movements con reason='sale'.
    """
    try:
        data = {k: v for k, v in patch.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        new_status = data.get("status")
        if new_status and new_status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Estado inválido. Válidos: {', '.join(sorted(VALID_STATUSES))}"
            )

        # Verificar estado actual antes de actualizar
        current_result = (
            supabase.table("orders")
            .select("id, status")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not current_result.data:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        current_status = current_result.data["status"]

        result = (
            supabase.table("orders")
            .update(data)
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        # ── Decremento de stock al confirmar (pending o pending_payment → confirmed) ──
        if new_status == "confirmed" and current_status in ("pending", "pending_payment"):
            _decrement_stock_on_confirm(supabase, order_id, tenant_id)

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar pedido")


@router.post("/{order_id}/payment-link", response_model=dict)
async def create_payment_link(
    order_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Genera un link de pago Wompi para un pedido en estado pending o pending_payment.
    Persiste el link en la tabla payments y retorna la checkout_url.
    Válido por WOMPI_PAYMENT_LINK_TTL_MINUTES minutos (default 30).
    """
    try:
        from integrations.wompi_client import create_payment_link as wompi_create_link, WOMPI_PRIVATE_KEY

        if not WOMPI_PRIVATE_KEY:
            raise HTTPException(
                status_code=503,
                detail="Integración Wompi no configurada (WOMPI_PRIVATE_KEY ausente)",
            )

        order_res = (
            supabase.table("orders")
            .select("id, status, total_amount, shipping_cost, notes, contact_id, contacts(name, phone)")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not order_res.data:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        order = order_res.data
        if order["status"] not in ("pending", "pending_payment"):
            raise HTTPException(
                status_code=409,
                detail=f"El pedido está en estado '{order['status']}' — solo se puede generar link para pedidos pending o pending_payment",
            )

        total_amount = float(order.get("total_amount") or 0)
        amount_in_cents = int(total_amount * 100)

        if amount_in_cents < 150000:  # mínimo $1.500 COP para modelo Agregador
            raise HTTPException(
                status_code=422,
                detail=f"Monto mínimo Wompi es $1.500 COP. Monto actual: ${total_amount:,.0f}",
            )

        contact = order.get("contacts") or {}
        contact_name = contact.get("name") or "Cliente"
        short_id = order_id[:8].upper()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=WOMPI_PAYMENT_LINK_TTL_MINUTES)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        link_data = await wompi_create_link(
            order_id=order_id,
            name=f"Pedido #{short_id} — {contact_name}"[:100],
            description=order.get("notes") or f"Pedido #{short_id}",
            amount_in_cents=amount_in_cents,
            expires_at=expires_at,
        )

        # Persistir en tabla payments
        supabase.table("payments").insert({
            "tenant_id": tenant_id,
            "order_id": order_id,
            "provider": "wompi",
            "wompi_link_id": link_data["link_id"],
            "checkout_url": link_data["checkout_url"],
            "amount_in_cents": amount_in_cents,
            "currency": "COP",
            "status": "pending",
            "wompi_status": "ACTIVE",
        }).execute()

        # Asegurar que el pedido quede en pending_payment
        if order["status"] != "pending_payment":
            supabase.table("orders").update({"status": "pending_payment"}).eq(
                "id", order_id
            ).eq("tenant_id", tenant_id).execute()

        logger.info(
            "Payment link generado para order %s: %s", order_id, link_data["checkout_url"]
        )
        return {
            "order_id": order_id,
            "checkout_url": link_data["checkout_url"],
            "amount_in_cents": amount_in_cents,
            "expires_at": expires_at,
            "wompi_link_id": link_data["link_id"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error generando payment link para order %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail=f"Error al generar link de pago: {e}")


def _decrement_stock_on_confirm(supabase: Client, order_id: str, tenant_id: str) -> None:
    """
    Decrementa stock de las variantes incluidas en el pedido al confirmarlo.
    Inserta registros en stock_movements para auditoría.
    Si una variante no tiene suficiente stock, se decrementa igualmente
    (permitir negativo — el operador verá el alerta de bajo stock).
    """
    try:
        items_result = (
            supabase.table("order_items")
            .select("variation_id, quantity")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        items = items_result.data or []

        for item in items:
            variation_id = item.get("variation_id")
            quantity = item.get("quantity", 0)
            if not variation_id or quantity <= 0:
                continue

            # Obtener stock actual
            var_result = (
                supabase.table("product_variations")
                .select("id, stock_quantity")
                .eq("id", variation_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            if not var_result.data:
                continue

            current_stock = var_result.data["stock_quantity"]
            new_stock = current_stock - quantity

            # Actualizar stock
            supabase.table("product_variations").update(
                {"stock_quantity": new_stock}
            ).eq("id", variation_id).eq("tenant_id", tenant_id).execute()

            # Registrar movimiento
            supabase.table("stock_movements").insert({
                "tenant_id": tenant_id,
                "variation_id": variation_id,
                "delta": -quantity,
                "new_stock": new_stock,
                "reason": "sale",
            }).execute()

            # Sync stock a MeLi si hay listing activo vinculado
            asyncio.ensure_future(sync_meli_stock(variation_id, new_stock, supabase))

    except Exception as e:
        # No fallar la confirmación del pedido si el stock no se puede decrementar
        logger.error(
            "Error decrementando stock para pedido %s: %s",
            order_id, e
        )
