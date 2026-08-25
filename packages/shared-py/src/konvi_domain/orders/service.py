"""OrdersService — dominio pedidos (Track 5 M2.1; contrato §4.1).

ÚNICA implementación de la lógica de negocio de pedidos, extraída intacta de
`services/api/routers/orders.py` (que queda como adaptador HTTP: dual-auth,
idempotency-key, audit decorator, mapeo de errores). Cada consulta, guard y
orden de operaciones es el heredado — el money-path no admite drift.

Reglas de la extracción (certificadas por tests/test_orders_channel_parity.py):
  - Misma secuencia de llamadas a supabase que el código original.
  - Mismos mensajes de error y códigos (DomainError → HTTPException en el router).
  - Efectos best-effort (stock al confirmar) se inyectan (`on_confirm_stock`)
    porque hoy viven acoplados a la integración MeLi del servicio API
    (`sync_meli_stock`) — cuando InventoryService aterrice (backlog M1 #3)
    solo cambia la implementación inyectada, no la semántica.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from konvi_domain.actor import Actor
from konvi_domain.errors import DomainError, ErrorCode
from konvi_domain.events import DomainEvent
from konvi_domain.orders.models import (
    ORDER_STATUS_RANK,
    ORDER_TERMINAL_STATUSES,
    PAYMENT_METHOD_COD,
    STATUS_PRESENTATION_ORDER,
    CreateOrderInput,
    CreateOrderResult,
    OrdersPage,
)

logger = logging.getLogger(__name__)

# Tipo del efecto inyectado: (supabase, order_id, tenant_id) -> None.
OnConfirmStock = Callable[[Any, str, str], None]


def is_allowed_order_transition(current: str, new: str) -> bool:
    """Máquina de estados (A11 ORD-01): forward-only + cancelable desde
    no-terminal + idempotente; un terminal NO se reabre."""
    if current == new:
        return True
    if current in ORDER_TERMINAL_STATUSES:
        return False
    if new == "cancelled":
        return True
    return ORDER_STATUS_RANK.get(new, 99) >= ORDER_STATUS_RANK.get(current, -1)


def create_order(
    supabase: Any,
    *,
    tenant_id: str,
    input: CreateOrderInput,
    actor: Actor,
    on_confirm_stock: Optional[OnConfirmStock] = None,
) -> CreateOrderResult:
    """Crea pedido con ítems. Total recomputado server-side (NUNCA del canal).

    Invariantes heredados (ver services/api/routers/orders.py histórico):
      - F1: el total incluye el descuento del cupón VIVO del cart de la
        conversación (cart-as-SoT ADR-0026): max(0, subtotal+shipping−descuento).
      - F27: ownership de FKs (contact/conversation/variations) antes del INSERT
        — anti-IDOR/fuga PII cross-tenant.
      - B1: índice único parcial anti doble-cobro + adopt-winner en 23505.
      - Rev.108: COD → confirmed inmediato; payment_link → pending_payment.
    """
    subtotal = sum(item.unit_price * item.quantity for item in input.items)
    discount_amount = 0.0
    if input.conversation_id:
        try:
            # BLOQUE A (P1): heredar el descuento SOLO de un cart no-terminal
            # (open/checkout) Y con una redención VIVA ('applied'). Un cart
            # 'converted'/'cancelled' conserva discount_cents stale
            # (consume_redemption no lo limpia); sin este guard, un segundo
            # pedido manual del operador para la misma conversación re-aplicaría
            # el mismo descuento (doble descuento / pedido en $0).
            cart_res = (
                supabase.table("conversation_carts")
                .select("id, status, discount_cents")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", input.conversation_id)
                .in_("status", ["open", "checkout"])
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if cart_res.data:
                _cart_row = cart_res.data[0]
                _dc = int(_cart_row.get("discount_cents") or 0)
                if _dc > 0:
                    _red = (
                        supabase.table("coupon_redemptions")
                        .select("id")
                        .eq("tenant_id", tenant_id)
                        .eq("cart_id", _cart_row["id"])
                        .eq("status", "applied")
                        .limit(1)
                        .execute()
                    )
                    if _red.data:
                        discount_amount = round(_dc / 100.0, 2)
        except Exception as exc:
            logger.warning(
                "[ORDER] lookup descuento del cart falló conv=%s: %s",
                input.conversation_id, exc,
            )
    total = max(0.0, subtotal + input.shipping_cost - discount_amount)

    # F27 (IDOR / fuga PII cross-tenant): validar ownership de los FK del input
    # ANTES del INSERT.
    if input.contact_id:
        _c = (
            supabase.table("contacts").select("id")
            .eq("id", input.contact_id).eq("tenant_id", tenant_id).limit(1).execute()
        )
        if not _c.data:
            raise DomainError(ErrorCode.NOT_FOUND, "Contacto no encontrado en este tenant")
    if input.conversation_id:
        _cv = (
            supabase.table("conversations").select("id")
            .eq("id", input.conversation_id).eq("tenant_id", tenant_id).limit(1).execute()
        )
        if not _cv.data:
            raise DomainError(ErrorCode.NOT_FOUND, "Conversación no encontrada en este tenant")

    # Lookup de cost_price (tenant-scoped) — ANTES del insert para (a) validar
    # que cada variation_id del input pertenezca al tenant y (b) reusarlo en items.
    variation_ids = [str(item.variation_id) for item in input.items if item.variation_id]
    variation_costs: dict[str, float] = {}
    if variation_ids:
        var_res = (
            supabase.table("product_variations")
            .select("id, cost_price")
            .eq("tenant_id", tenant_id)
            .in_("id", variation_ids)
            .execute()
        )
        variation_costs = {v["id"]: float(v["cost_price"] or 0) for v in (var_res.data or [])}
    for item in input.items:
        if item.variation_id and str(item.variation_id) not in variation_costs:
            raise DomainError(ErrorCode.VALIDATION, "variation_id no pertenece a este tenant")

    # Rev. 108 Fase B — COD bypass: si payment_method='cod', orden directo
    # confirmed (no hay pago anticipado a esperar). payment_link se ignora en COD.
    if input.payment_method == PAYMENT_METHOD_COD:
        initial_status = "confirmed"
    else:
        initial_status = "pending_payment" if input.payment_link else "pending"

    # B1 (auditoría money-path 2026-08-21): el índice único parcial
    # uq_orders_one_pending_payment_per_conversation cierra la carrera de dos
    # turnos concurrentes creando dos órdenes pagables para la misma
    # conversación. El insert perdedor (23505) ADOPTA la orden ganadora.
    try:
        order_result = supabase.table("orders").insert({
            "tenant_id": tenant_id,
            "contact_id": input.contact_id,
            "conversation_id": input.conversation_id,
            "status": initial_status,
            "total_amount": total,
            "discount_amount": discount_amount,  # F1: snapshot del descuento para trazabilidad
            "shipping_cost": input.shipping_cost,
            "notes": input.notes,
            "payment_method": input.payment_method,
        }).execute()
    except Exception as insert_exc:
        _winner = None
        _emsg = str(insert_exc)
        if (
            ("23505" in _emsg or "duplicate" in _emsg.lower())
            and input.conversation_id
            and initial_status == "pending_payment"
        ):
            try:
                _wres = (
                    supabase.table("orders")
                    .select("*")
                    .eq("tenant_id", tenant_id)
                    .eq("conversation_id", input.conversation_id)
                    .eq("status", "pending_payment")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                _winner = (_wres.data or [None])[0]
            except Exception:
                _winner = None
        if not isinstance(_winner, dict) or not _winner.get("id"):
            raise  # no era la carrera B1 → propagar el error original
        # Adopt-winner: responder la orden ganadora con sus items reales
        # (mismo shape que el happy path + marca adopted_existing).
        _winner_items: list = []
        try:
            _wi = (
                supabase.table("order_items")
                .select("order_id, tenant_id, product_id, variation_id, "
                        "title, unit_price, unit_cost, quantity")
                .eq("order_id", _winner["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            _winner_items = _wi.data or []
        except Exception as _wi_exc:
            logger.warning(
                "[ORDER] B1 adopt-winner: no pude leer items de %s: %s",
                _winner["id"], _wi_exc,
            )
        logger.warning(
            "[ORDER] B1 adopt-winner: carrera 23505 conv=%s — reuso orden ganadora %s "
            "en vez de duplicar",
            input.conversation_id, _winner["id"],
        )
        return CreateOrderResult(
            order=_winner,
            items=_winner_items,
            adopted_existing=True,
            http_status=200,
            events=(DomainEvent("order.adopted_existing", {
                "order_id": _winner["id"], "conversation_id": input.conversation_id,
            }),),
        )

    if not order_result.data:
        raise DomainError(ErrorCode.UPSTREAM, "Error al crear pedido")

    order_row = order_result.data[0]
    order_id = order_row["id"]

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
        for item in input.items
    ]
    supabase.table("order_items").insert(items_data).execute()

    result = CreateOrderResult(
        order=order_row,
        items=items_data,
        events=(DomainEvent("order.created", {
            "order_id": order_id, "tenant_id": tenant_id,
            "status": initial_status, "total_amount": total,
            "discount_amount": discount_amount,
            "payment_method": input.payment_method,
            "channel": actor.channel.value,
        }),),
    )

    # Rev. 108 Fase B — COD: consumir stock inmediatamente (orden ya está
    # confirmed). Mismo path que auto_confirm + Wompi APPROVED. Best-effort
    # heredado: un fallo NO tumba la creación (se loguea).
    if input.payment_method == PAYMENT_METHOD_COD:
        try:
            if on_confirm_stock is not None:
                on_confirm_stock(supabase, order_id, tenant_id)
            logger.info(
                "Pedido COD %s creado confirmed + stock decrementado tenant=%s",
                order_id, tenant_id,
            )
        except Exception as ce:
            logger.error(
                "Error decrementando stock pedido COD %s: %s", order_id, ce,
            )

    # Confirmar de inmediato si el canal lo solicita (Inbox flow).
    elif input.auto_confirm:
        try:
            (
                supabase.table("orders")
                .update({"status": "confirmed"})
                .eq("id", order_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if on_confirm_stock is not None:
                on_confirm_stock(supabase, order_id, tenant_id)
            result.order["status"] = "confirmed"
            logger.info("Pedido %s auto-confirmado desde Inbox (stock decrementado)", order_id)
        except Exception as ce:
            logger.error("Error auto-confirmando pedido %s: %s", order_id, ce)
            # No fallar la creación — el pedido quedó en pending

    return result


def get_order(supabase: Any, *, tenant_id: str, order_id: str, actor: Actor) -> dict:
    """Detalle del pedido con ítems y datos del contacto (shape heredado)."""
    result = (
        supabase.table("orders")
        .select("*, contacts(phone, name), order_items(id, title, unit_price, unit_cost, quantity, product_id, variation_id)")
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        # F19: .limit(1) + unwrap (no .single()) → NOT_FOUND correcto en vez de 500.
        .limit(1)
        .execute()
    )
    row = (result.data or [None])[0]
    if not row:
        raise DomainError(ErrorCode.NOT_FOUND, "Pedido no encontrado")
    return row


def list_orders(
    supabase: Any,
    *,
    tenant_id: str,
    actor: Actor,
    status: Optional[str] = None,
    contact_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> OrdersPage:
    """Listado paginado de pedidos del tenant (consola) + conteos por estado.

    Semántica heredada de la página orders (D7/D9):
      - `q` resuelve contactos por nombre/teléfono (ilike ×2, cap 200) y filtra
        por ese conjunto; búsqueda sin coincidencias → lista vacía.
      - Los conteos por estado (badges) usan lente tenant + contacto — el texto
        de búsqueda NO afecta las pestañas (reflejan la distribución real).
    """
    search_contact_ids: Optional[list[str]] = None
    if q:
        by_name = (
            supabase.table("contacts").select("id")
            .eq("tenant_id", tenant_id).ilike("name", f"%{q}%").limit(200).execute()
        )
        by_phone = (
            supabase.table("contacts").select("id")
            .eq("tenant_id", tenant_id).ilike("phone", f"%{q}%").limit(200).execute()
        )
        search_contact_ids = list({
            *(r["id"] for r in (by_name.data or [])),
            *(r["id"] for r in (by_phone.data or [])),
        })

    list_query = (
        supabase.table("orders")
        .select(
            "id, status, total_amount, discount_amount, shipping_cost, notes, "
            "created_at, payment_method, contacts(id, phone, name), "
            "order_items(title, quantity, unit_price)",
            count="exact",
        )
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status:
        list_query = list_query.eq("status", status)
    if contact_id:
        list_query = list_query.eq("contact_id", contact_id)
    if search_contact_ids is not None:
        if not search_contact_ids:
            # Búsqueda sin coincidencias → resultado vacío (guard con id imposible,
            # mismo patrón heredado de la página).
            list_query = list_query.eq("contact_id", "00000000-0000-0000-0000-000000000000")
        else:
            list_query = list_query.in_("contact_id", search_contact_ids)

    def _count_base():
        cq = supabase.table("orders").select("id", count="exact", head=True).eq("tenant_id", tenant_id)
        if contact_id:
            cq = cq.eq("contact_id", contact_id)
        return cq

    list_res = list_query.execute()
    all_count_res = _count_base().execute()
    status_count_res = {s: _count_base().eq("status", s).execute() for s in STATUS_PRESENTATION_ORDER}

    counts = {"all": getattr(all_count_res, "count", 0) or 0}
    for s in STATUS_PRESENTATION_ORDER:
        counts[s] = getattr(status_count_res[s], "count", 0) or 0

    return OrdersPage(
        orders=list_res.data or [],
        total=getattr(list_res, "count", 0) or 0,
        counts=counts,
    )


def list_orders_by_contact(
    supabase: Any,
    *,
    tenant_id: str,
    contact_id: str,
    actor: Actor,
    since_days: int = 30,
    limit: int = 5,
) -> list[dict]:
    """Historial reciente de pedidos de un contacto (bot M3 + consola).

    Cubre el hueco del contrato (M1 §3.3): hoy esta lectura existe solo dentro
    del bot (`agentic/tools/orders.py`). Con items embedidos en UNA query (el
    bot hacía lookup aparte); el enriquecimiento con shipment queda para el
    adaptador del bot en M3 (no es parte del read canónico).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    res = (
        supabase.table("orders")
        .select(
            "id, status, total_amount, shipping_cost, created_at, updated_at, notes, "
            "order_items(id, title, unit_price, quantity)"
        )
        .eq("tenant_id", tenant_id)
        .eq("contact_id", contact_id)
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []
