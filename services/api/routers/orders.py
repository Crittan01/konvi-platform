"""
Router de Pedidos — CRUD con aislamiento multi-tenant via RLS.

Endpoints:
  GET    /api/v1/orders/          — listar pedidos del tenant
  POST   /api/v1/orders/          — crear pedido con ítems   [owner, manager]
  GET    /api/v1/orders/{id}      — detalle con ítems
  PATCH  /api/v1/orders/{id}      — cambiar estado / notas   [owner, manager]

Estados válidos: pending → confirmed → processing → shipped → delivered | cancelled
"""
import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from routers.marketplace import sync_meli_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])

VALID_STATUSES = {"pending", "confirmed", "processing", "shipped", "delivered", "cancelled"}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class OrderItemCreate(BaseModel):
    product_id: Optional[str] = None
    variation_id: Optional[str] = None
    title: str = Field(..., min_length=1)
    unit_price: float = Field(..., gt=0)
    unit_cost: Optional[float] = None
    quantity: int = Field(default=1, ge=1)


class OrderCreate(BaseModel):
    contact_id: Optional[str] = None
    conversation_id: Optional[str] = None
    notes: Optional[str] = None
    shipping_cost: float = Field(default=0.0, ge=0.0)
    items: List[OrderItemCreate] = Field(..., min_length=1)


class OrderPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


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
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea pedido con ítems. Calcula total automáticamente. Solo owner/manager."""
    try:
        total = sum(item.unit_price * item.quantity for item in order.items) + order.shipping_cost

        order_result = supabase.table("orders").insert({
            "tenant_id": tenant_id,
            "contact_id": order.contact_id,
            "conversation_id": order.conversation_id,
            "status": "pending",
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

        return {**order_result.data[0], "items": items_data}
    except HTTPException:
        raise
    except Exception as e:
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
            .select("*, contacts(phone, name), order_items(id, title, unit_price, quantity, product_id)")
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

        # ── Decremento de stock al confirmar (pending → confirmed) ─────────────
        if new_status == "confirmed" and current_status == "pending":
            _decrement_stock_on_confirm(supabase, order_id, tenant_id)

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar pedido")


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
