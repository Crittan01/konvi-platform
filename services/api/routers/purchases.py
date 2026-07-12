"""
Router de Compras / Purchases — proveedores + órdenes de compra con WAC.

Rev. 72 — cierra el drift D2 (Purchases escribía directo a DB desde RSC).

Endpoints:
  GET    /api/v1/purchases/suppliers          — listar proveedores             [todos]
  POST   /api/v1/purchases/suppliers          — crear proveedor                [owner]
  PATCH  /api/v1/purchases/suppliers/{id}     — editar / (des)activar          [owner]
  GET    /api/v1/purchases/                   — listar órdenes de compra       [todos]
  POST   /api/v1/purchases/                   — crear OC con items[]           [owner]
  GET    /api/v1/purchases/{po_id}            — detalle con items
  PATCH  /api/v1/purchases/{po_id}            — editar OC en 'ordered'
                                                (cantidades/costos/fecha)       [owner]
  POST   /api/v1/purchases/{po_id}/cancel     — cancelar OC pendiente          [owner]
  POST   /api/v1/purchases/{po_id}/receive    — marcar recibida + actualizar
                                                stock + WAC determinístico     [owner]

RBAC (F3 — cierre de drift): la escritura en Compras es owner-only, alineada con
sidebar-client.tsx (Compras oculto a manager). El módulo expone costos/márgenes del
tenant; ampliar a manager es una decisión de confianza reservada al founder.

Estados PO válidos: ordered → received | cancelled. (Se podaron 'draft'/'in_transit':
el backend nunca los emite y la recepción es todo-o-nada; prometer estados muertos
confunde al operador. Ver migración 20260704153000 para el CHECK tightening opcional.)

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
    require_owner_role,
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


class SupplierUpdate(BaseModel):
    """Edición parcial de proveedor. Todos los campos opcionales; se persiste solo
    lo provisto. `is_active=False` = soft-delete (nunca hard-delete: purchase_orders
    referencia al proveedor y borrarlo destruiría el historial de compras)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=180)
    contact_email: Optional[str] = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(default=None, pattern=r"^[0-9]{10}$")
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=365)
    is_active: Optional[bool] = None


class POItemCreate(BaseModel):
    variation_id: str = Field(..., description="UUID de product_variations")
    quantity: int = Field(..., gt=0)
    unit_cost: float = Field(..., gt=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    items: List[POItemCreate] = Field(..., min_length=1)
    expected_date: Optional[str] = None  # ISO 8601


class PurchaseOrderUpdate(BaseModel):
    """Edición de una OC en estado 'ordered' (corregir cantidades/costos antes de
    recibir). `items` reemplaza el set completo de ítems (no es un merge parcial:
    la UI reenvía la lista editada). `expected_date` opcional. Al menos uno debe
    venir. Solo aplicable mientras la OC está 'ordered' — recibida/cancelada es
    inmutable (el stock/WAC ya se aplicó o la OC se cerró)."""
    items: Optional[List[POItemCreate]] = Field(default=None, min_length=1)
    expected_date: Optional[str] = None  # ISO 8601


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ensure_supplier_belongs_to_tenant(supabase: Client, tenant_id: str, supplier_id: str) -> None:
    res = (
        supabase.table("suppliers")
        .select("id")
        .eq("id", supplier_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
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
    include_inactive: bool = Query(default=False),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    # BLOQUE F-1: los datos financieros de compras (proveedores, costos, márgenes) son OWNER-ONLY
    # (decisión founder). Antes los GET no tenían guard → manager/operator veían costos/márgenes.
    _role: str = Depends(require_owner_role),
):
    res = (
        supabase.table("suppliers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("name", desc=False)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    # Filtro de activos en Python (no en el WHERE) para degradar seguro si la
    # columna `is_active` aún no existe: r.get(..., True) → un proveedor sin la
    # columna se trata como activo. Con la migración aplicada, filtra soft-deleted.
    if not include_inactive:
        rows = [r for r in rows if r.get("is_active", True)]
    return rows


@router.post("/suppliers", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="supplier", action="created")
async def create_supplier(
    body: SupplierCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
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


_MISSING_COLUMN_HINTS = ("is_active", "column", "schema cache", "pgrst204", "42703")


@router.patch("/suppliers/{supplier_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="supplier", action="updated")
async def update_supplier(
    supplier_id: str,
    body: SupplierUpdate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """Edición parcial + soft-delete (is_active). NO hard-delete: el proveedor está
    referenciado por purchase_orders; borrarlo destruye el historial de compras."""
    _ensure_supplier_belongs_to_tenant(supabase, tenant_id, supplier_id)

    payload: dict = {}
    if body.name is not None:
        payload["name"] = body.name.strip()
    if body.contact_email is not None:
        payload["contact_email"] = body.contact_email
    if body.phone is not None:
        payload["phone"] = body.phone
    if body.lead_time_days is not None:
        payload["lead_time_days"] = body.lead_time_days
    if body.is_active is not None:
        payload["is_active"] = body.is_active

    if not payload:
        raise HTTPException(status_code=422, detail="No hay cambios para guardar")

    try:
        res = (
            supabase.table("suppliers")
            .update(payload)
            .eq("id", supplier_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — degradar seguro si falta la columna is_active
        msg = str(exc).lower()
        if body.is_active is not None and any(h in msg for h in _MISSING_COLUMN_HINTS):
            logger.warning("[PURCHASES] update_supplier: columna is_active ausente (migración pendiente)")
            raise HTTPException(
                status_code=409,
                detail="Activar/desactivar proveedores requiere una migración pendiente. Contacta al administrador.",
            ) from exc
        raise
    if not res.data:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado para este tenant")
    return res.data[0]


# ─── Endpoints: Purchase Orders ──────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_purchase_orders(
    status: Optional[str] = Query(default=None),
    supplier_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),  # F-1: compras owner-only
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
    _role: str = Depends(require_owner_role),
):
    """Crea PO con items[]. Valida supplier y todas las variations del tenant.
    Total se calcula server-side (no del cliente) — defensa contra manipulación."""
    _ensure_supplier_belongs_to_tenant(supabase, tenant_id, body.supplier_id)
    _ensure_variations_belong_to_tenant(supabase, tenant_id, [i.variation_id for i in body.items])

    total_amount = sum(i.quantity * i.unit_cost for i in body.items)

    # F-doc (Fase 6): .insert() en postgrest 2.28.3 devuelve SyncQueryRequestBuilder
    # SIN .select()/.single() — el chain '.insert().select("*").single()' lanzaba
    # AttributeError → create_purchase_order roto al 100%. Mismo bug que F18 cerró en
    # knowledge_base.py:151 pero omitió aquí. insert ya retorna representation → data[0].
    po_res = supabase.table("purchase_orders").insert({
        "tenant_id":     tenant_id,
        "supplier_id":   body.supplier_id,
        "status":        "ordered",
        "expected_date": body.expected_date,
        "total_amount":  total_amount,
    }).execute()
    if not po_res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear la OC")
    po = po_res.data[0]

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
    _role: str = Depends(require_owner_role),  # F-1: compras owner-only
):
    po_res = (
        supabase.table("purchase_orders")
        .select("*")
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not po_res or not po_res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="OC no encontrada")
    items_res = (
        supabase.table("purchase_order_items")
        .select("*")
        .eq("po_id", po_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return {**po_res.data, "items": items_res.data or []}


@router.patch("/{po_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="purchase_order", action="updated")
async def update_purchase_order(
    po_id: str,
    body: PurchaseOrderUpdate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """Corrige una OC en estado 'ordered' (cantidades/costos/fecha) ANTES de
    recibirla — evita el ciclo cancelar+re-digitar. Solo mutable en 'ordered':
    recibida ya aplicó stock/WAC; cancelada está cerrada.

    `items` (si viene) reemplaza el set completo: se validan las variations del
    tenant, se recalcula total_amount server-side y se reescriben los ítems. El
    UPDATE del encabezado lleva guard `.eq("status","ordered")` para idempotencia
    y para no editar una OC que cambió de estado entre el GET y el PATCH (409)."""
    if body.items is None and body.expected_date is None:
        raise HTTPException(status_code=422, detail="No hay cambios para guardar")

    # 1) La OC debe existir, pertenecer al tenant y estar en 'ordered'.
    po_res = (
        supabase.table("purchase_orders")
        .select("id, status")
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not po_res or not po_res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="OC no encontrada")
    if po_res.data.get("status") != "ordered":
        raise HTTPException(
            status_code=409,
            detail="Solo se puede editar una OC pendiente (no recibida ni cancelada)",
        )

    header_update: dict = {}
    if body.expected_date is not None:
        header_update["expected_date"] = body.expected_date

    # 2) Si vienen ítems: validar variations + recalcular total server-side.
    if body.items is not None:
        _ensure_variations_belong_to_tenant(
            supabase, tenant_id, [i.variation_id for i in body.items]
        )
        header_update["total_amount"] = sum(i.quantity * i.unit_cost for i in body.items)

    # 3) Actualizar encabezado con guard de estado (idempotencia + carrera GET→PATCH).
    upd = (
        supabase.table("purchase_orders")
        .update(header_update)
        .eq("id", po_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "ordered")
        .execute()
    )
    if not upd.data:
        raise HTTPException(
            status_code=409,
            detail="La OC cambió de estado y ya no se puede editar. Refresca la página.",
        )

    # 4) Reemplazar ítems (delete + insert) SOLO tras confirmar el guard del header.
    if body.items is not None:
        supabase.table("purchase_order_items").delete().eq("po_id", po_id).eq(
            "tenant_id", tenant_id
        ).execute()
        items_payload = [{
            "tenant_id":    tenant_id,
            "po_id":        po_id,
            "variation_id": i.variation_id,
            "quantity":     i.quantity,
            "unit_cost":    i.unit_cost,
        } for i in body.items]
        supabase.table("purchase_order_items").insert(items_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id

    return upd.data[0]


@router.post("/{po_id}/cancel", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="purchase_order", action="status_changed")
async def cancel_purchase_order(
    po_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
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
    _role: str = Depends(require_owner_role),
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
