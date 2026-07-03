"""
Router de Compras / Purchases — proveedores + órdenes de compra con WAC.

Rev. 72 — cierra el drift D2 (Purchases escribía directo a DB desde RSC).

Endpoints:
  GET    /api/v1/purchases/suppliers          — listar proveedores             [todos]
  POST   /api/v1/purchases/suppliers          — crear proveedor                [owner, manager]
  GET    /api/v1/purchases/                   — listar órdenes de compra       [todos]
  POST   /api/v1/purchases/                   — crear OC con items[]           [owner, manager]
  GET    /api/v1/purchases/{po_id}            — detalle con items
  POST   /api/v1/purchases/{po_id}/cancel     — cancelar OC pendiente          [owner, manager]
  POST   /api/v1/purchases/{po_id}/receive    — marcar recibida + actualizar
                                                stock + WAC determinístico     [owner, manager]

Estados PO válidos: ordered → received | cancelled.

WAC (Weighted Average Cost) — fórmula determinística aplicada al recibir:
    new_cost = ((max(0, old_stock) * old_cost) + (po_qty * po_cost)) / (max(0, old_stock) + po_qty)
Stock se incrementa en `po_qty`. Movement de stock se registra con reason='purchase_restock'.
Idempotencia: la transición 'ordered' → 'received' solo aplica si el PO está en 'ordered'
(condición en el UPDATE evita doble recibo).
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Purchases"])

VALID_PO_STATUSES = {"ordered", "received", "cancelled"}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=180)
    contact_email: Optional[str] = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(default=None, pattern=r"^[0-9]{10}$")
    lead_time_days: Optional[int] = Field(default=0, ge=0, le=365)


class POItemCreate(BaseModel):
    variation_id: str = Field(..., description="UUID de product_variations")
    quantity: int = Field(..., gt=0)
    unit_cost: float = Field(..., gt=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    items: List[POItemCreate] = Field(..., min_length=1)
    expected_date: Optional[str] = None  # ISO 8601


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ensure_supplier_belongs_to_tenant(supabase: Client, tenant_id: str, supplier_id: str) -> None:
    res = (
        supabase.table("suppliers")
        .select("id")
        .eq("id", supplier_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado para este tenant")


def _ensure_variations_belong_to_tenant(supabase: Client, tenant_id: str, variation_ids: list[str]) -> dict[str, str]:
    """Devuelve mapa variation_id → product_id. Lanza 404 si alguna no pertenece."""
    res = (
        supabase.table("product_variations")
        .select("id, product_id")
        .eq("tenant_id", tenant_id)
        .in_("id", variation_ids)
        .execute()
    )
    found = {r["id"]: r["product_id"] for r in (res.data or [])}
    missing = set(variation_ids) - set(found.keys())
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Variantes no encontradas para este tenant: {sorted(missing)}",
        )
    return found


def _compute_wac(old_stock: int, old_cost: float, po_qty: int, po_cost: float) -> float:
    """Weighted Average Cost determinístico. Maneja stock negativo (saneado a 0)."""
    effective_stock = max(0, old_stock)
    denom = effective_stock + po_qty
    if denom <= 0:
        return po_cost
    return ((effective_stock * old_cost) + (po_qty * po_cost)) / denom


# ─── Endpoints: Suppliers ────────────────────────────────────────────────────

@router.get("/suppliers", response_model=List[dict])
async def list_suppliers(
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    res = (
        supabase.table("suppliers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("name", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


@router.post("/suppliers", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="supplier", action="created")
async def create_supplier(
    body: SupplierCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    payload = {
        "tenant_id":      tenant_id,
        "name":           body.name.strip(),
        "contact_email":  body.contact_email,
        "phone":          body.phone,
        "lead_time_days": body.lead_time_days or 0,
    }
    res = supabase.table("suppliers").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    if not res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear el proveedor")
    return res.data[0]


# ─── Endpoints: Purchase Orders ──────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_purchase_orders(
    status: Optional[str] = Query(default=None),
    supplier_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    q = supabase.table("purchase_orders").select("*").eq("tenant_id", tenant_id)
    if status:
        if status not in VALID_PO_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Status inválido. Válidos: {sorted(VALID_PO_STATUSES)}",
            )
        q = q.eq("status", status)
    if supplier_id:
        q = q.eq("supplier_id", supplier_id)
    res = q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


@router.post("/", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="purchase_order", action="created")
async def create_purchase_order(
    body: PurchaseOrderCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea PO con items[]. Valida supplier y todas las variations del tenant.
    Total se calcula server-side (no del cliente) — defensa contra manipulación."""
    _ensure_supplier_belongs_to_tenant(supabase, tenant_id, body.supplier_id)
    _ensure_variations_belong_to_tenant(supabase, tenant_id, [i.variation_id for i in body.items])

    total_amount = sum(i.quantity * i.unit_cost for i in body.items)

    po_res = supabase.table("purchase_orders").insert({
        "tenant_id":     tenant_id,
        "supplier_id":   body.supplier_id,
        "status":        "ordered",
        "expected_date": body.expected_date,
        "total_amount":  total_amount,
    }).select("*").single().execute()
    if not po_res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear la OC")
    po = po_res.data

    items_payload = [{
        "tenant_id":    tenant_id,
        "po_id":        po["id"],
        "variation_id": i.variation_id,
        "quantity":     i.quantity,
        "unit_cost":    i.unit_cost,
    } for i in body.items]
    supabase.table("purchase_order_items").insert(items_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id

    return po


@router.get("/{po_id}", response_model=dict)
async def get_purchase_order(
    po_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    po_res = (
        supabase.table("purchase_orders")
        .select("*")
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not po_res.data:
        raise HTTPException(status_code=404, detail="OC no encontrada")
    items_res = (
        supabase.table("purchase_order_items")
        .select("*")
        .eq("po_id", po_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return {**po_res.data, "items": items_res.data or []}


@router.post("/{po_id}/cancel", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="purchase_order", action="status_changed")
async def cancel_purchase_order(
    po_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Cancela OC en estado 'ordered'. Idempotente: solo afecta filas en 'ordered'."""
    res = (
        supabase.table("purchase_orders")
        .update({"status": "cancelled"})
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "ordered")
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=409,
            detail="OC no se puede cancelar (no existe o ya está received/cancelled)",
        )
    return res.data[0]


@router.post("/{po_id}/receive", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="purchase_order", action="status_changed")
async def receive_purchase_order(
    po_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Marca OC como received + actualiza stock y WAC + crea stock_movements.
    Idempotente: el UPDATE 'ordered' → 'received' solo aplica si está en 'ordered'."""
    items_res = (
        supabase.table("purchase_order_items")
        .select("variation_id, quantity, unit_cost")
        .eq("po_id", po_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    items = items_res.data or []
    if not items:
        raise HTTPException(status_code=404, detail="OC sin items")

    # 1) Mark as received con guard de estado para idempotencia.
    po_update = (
        supabase.table("purchase_orders")
        .update({"status": "received"})
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "ordered")
        .execute()
    )
    if not po_update.data:
        raise HTTPException(
            status_code=409,
            detail="OC no se puede recibir (no existe o ya está received/cancelled)",
        )

    # 2) Recalcular stock + WAC + movement por cada item.
    for item in items:
        var_res = (
            supabase.table("product_variations")
            .select("stock_quantity, cost_price, product_id")
            .eq("id", item["variation_id"])
            .eq("tenant_id", tenant_id)
            # F19: .limit(1) en vez de .single() — con .single(), una variación borrada hacía que
            # execute() lanzara APIError (PGRST116) SIN try/except → 500 DESPUÉS de marcar la PO
            # 'received' → stock aplicado parcial (corrupción no-atómica). El `continue` era inalcanzable.
            .limit(1)
            .execute()
        )
        var_row = (var_res.data or [None])[0]
        if not var_row:
            logger.warning("[PURCHASES] receive: variation %s no existe; skip", item["variation_id"])
            continue
        old_stock = int(var_row.get("stock_quantity") or 0)
        old_cost = float(var_row.get("cost_price") or 0.0)
        po_qty = int(item["quantity"])
        po_cost = float(item["unit_cost"])
        new_stock = max(0, old_stock) + po_qty
        new_wac = _compute_wac(old_stock, old_cost, po_qty, po_cost)

        supabase.table("product_variations").update({
            "stock_quantity": new_stock,
            "cost_price":     new_wac,
        }).eq("id", item["variation_id"]).eq("tenant_id", tenant_id).execute()

        supabase.table("stock_movements").insert({
            "tenant_id":    tenant_id,
            "variation_id": item["variation_id"],
            "product_id":   var_row.get("product_id"),
            "delta":        po_qty,
            "new_stock":    new_stock,
            "reason":       "purchase_restock",
        }).execute()

    return po_update.data[0]
