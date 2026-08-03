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
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    WRITE_ROLES,
    enforce_mfa,
    get_current_role,
    get_current_tenant,
    get_service_client,
)
from dependencies.idempotency import (
    abort_idempotency,
    begin_idempotency,
    finalize_idempotency,
    payload_fingerprint,
)
from dependencies.internal_auth import (
    enforce_mfa_internal_or_user,
    get_role_internal_or_user,
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
    require_write_internal_or_user,
)
from dependencies.plans import PLAN_ORDERS_CREATE
from dependencies.security import RL_WRITE_DEFAULT
from integrations.wompi_client import payment_link_ttl_minutes
from routers.marketplace import sync_meli_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])

VALID_STATUSES = {"pending", "pending_payment", "confirmed", "processing", "shipped", "delivered", "cancelled"}

# A11 audit ORD-01: máquina de estados de la orden. patch_order validaba
# pertenencia al set pero NO la transición → permitía saltos inválidos
# (delivered→pending). Lifecycle: pending|pending_payment → confirmed →
# processing → shipped → delivered | cancelled. Regla conservadora (no rompe
# flujos legítimos): forward (rank no decrece) + cancelar desde cualquier
# no-terminal + idempotente; rechaza backward y reabrir un estado terminal.
_ORDER_STATUS_RANK = {
    "pending": 0, "pending_payment": 0,
    "confirmed": 1, "processing": 2, "shipped": 3, "delivered": 4,
}
_ORDER_TERMINAL_STATUSES = {"delivered", "cancelled"}


def _is_allowed_order_transition(current: str, new: str) -> bool:
    if current == new:
        return True  # idempotente
    if current in _ORDER_TERMINAL_STATUSES:
        return False  # un estado terminal NO se reabre
    if new == "cancelled":
        return True  # cancelable desde cualquier estado no-terminal
    return _ORDER_STATUS_RANK.get(new, 99) >= _ORDER_STATUS_RANK.get(current, -1)


# TTL de validez del link Wompi (expires_at enviado al crear el link): ÚNICA
# fuente `integrations.wompi_client.payment_link_ttl_minutes()` (env
# WOMPI_PAYMENT_LINK_TTL_MINUTES, default 30) — compartida con la regeneración
# de wompi_webhook.py. Antes aquí había un 30 hardcodeado que divergía del env.
# Detalles + espejos (payment_link_tool, PAYMENT_REMINDER_DELAY_MINUTES):
# ver el comentario junto a DEFAULT_PAYMENT_LINK_TTL_MINUTES en wompi_client.py.


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
    # Rev. 108 Fase B — modalidad de pago. 'credit' (default, vía Wompi) o
    # 'cod' (contraentrega, courier recauda al entregar). Si 'cod':
    #   • No se genera link Wompi (payment_link ignorado).
    #   • Orden se crea con status='confirmed' (consumo stock inmediato).
    #   • Generación de guía Aveonline con contraentrega=1 ocurre downstream.
    payment_method: str = Field(default="credit", pattern="^(credit|cod)$")


class OrderPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1200)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="order", action="created")
def create_order(
    order: OrderCreate,
    request: Request,
    # A0.2c dual-auth: acepta JWT user (Tenant Console) o INTERNAL_SERVICE_SECRET
    # header + X-Tenant-Id (orchestrator → api).
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
    supabase: Client = Depends(get_service_client_internal_or_user),
    # F2 RBAC (business_call founder-aprobado): operator es la persona principal
    # del módulo Pedidos → puede CREAR pedidos (crear no mueve dinero irreversible:
    # COD/credit arrancan pending/confirmed sin refund). get_role_internal_or_user
    # admite owner|manager|operator (RUNTIME_ROLES) y sigue devolviendo 'owner' al
    # tráfico internal-service. Las operaciones con dinero irreversible (cancelar
    # confirmado→refund, payment-link) permanecen owner/manager (ver patch_order y
    # create_payment_link).
    _role: str = Depends(get_role_internal_or_user),
    _plan: object = Depends(PLAN_ORDERS_CREATE),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Crea pedido con ítems. Calcula total automáticamente. owner/manager/operator."""
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

        # F1 (coherencia de dinero, 2026-07-02): el total DEBE incluir el descuento del cupón aplicado en el
        # cart (cart-as-SoT, ADR-0026). Antes se recomponía sin descuento → orders.total_amount quedaba pleno
        # y Wompi cobraba de más (el cliente veía el total CON descuento vía GetCartTool). Se lee el descuento
        # del cart de esta conversación y se espeja la fórmula del cart (cart_tool.py): max(0, subtotal+shipping-descuento).
        subtotal = sum(item.unit_price * item.quantity for item in order.items)
        discount_amount = 0.0
        if order.conversation_id:
            try:
                # BLOQUE A (P1): heredar el descuento SOLO de un cart no-terminal
                # (open/checkout) Y con una redención VIVA ('applied'). Un cart
                # 'converted'/'cancelled' conserva discount_cents stale (consume_redemption
                # no lo limpia); sin este guard, un segundo pedido manual del operador para
                # la misma conversación re-aplicaría el mismo descuento (doble descuento /
                # pedido en $0). La redención 'applied' es la señal autoritativa del cupón vivo.
                cart_res = (
                    supabase.table("conversation_carts")
                    .select("id, status, discount_cents")
                    .eq("tenant_id", tenant_id)
                    .eq("conversation_id", order.conversation_id)
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
                logger.warning("[ORDER] lookup descuento del cart falló conv=%s: %s", order.conversation_id, exc)
        total = max(0.0, subtotal + order.shipping_cost - discount_amount)

        # F27 (IDOR / fuga PII cross-tenant): validar ownership de los FK del body ANTES del INSERT.
        # Sin esto un order del tenant A podía apuntar a contact_id/conversation_id de OTRO tenant, y los
        # embeds PostgREST de get_order/create_payment_link (contacts(name,phone,email,documento)) seguían
        # el FK sin re-filtrar tenant → fuga de PII (incl. cédula, Ley 1581).
        if order.contact_id:
            _c = (
                supabase.table("contacts").select("id")
                .eq("id", order.contact_id).eq("tenant_id", tenant_id).limit(1).execute()
            )
            if not _c.data:
                raise HTTPException(status_code=404, detail="Contacto no encontrado en este tenant")
        if order.conversation_id:
            _cv = (
                supabase.table("conversations").select("id")
                .eq("id", order.conversation_id).eq("tenant_id", tenant_id).limit(1).execute()
            )
            if not _cv.data:
                raise HTTPException(status_code=404, detail="Conversación no encontrada en este tenant")

        # Lookup de cost_price (tenant-scoped) — ANTES del insert para (a) validar que cada variation_id
        # del body pertenezca al tenant y (b) reusarlo en items_data.
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
        for item in order.items:
            if item.variation_id and str(item.variation_id) not in variation_costs:
                raise HTTPException(status_code=422, detail="variation_id no pertenece a este tenant")

        # Rev. 108 Fase B — COD bypass: si payment_method='cod', orden directo
        # confirmed (no hay pago anticipado a esperar). payment_link flag
        # se ignora en COD.
        if order.payment_method == "cod":
            initial_status = "confirmed"
        else:
            initial_status = (
                "pending_payment" if order.payment_link else "pending"
            )
        order_result = supabase.table("orders").insert({
            "tenant_id": tenant_id,
            "contact_id": order.contact_id,
            "conversation_id": order.conversation_id,
            "status": initial_status,
            "total_amount": total,
            "discount_amount": discount_amount,   # F1: snapshot del descuento (moneda) para trazabilidad + coherencia
            "shipping_cost": order.shipping_cost,
            "notes": order.notes,
            "payment_method": order.payment_method,
        }).execute()

        if not order_result.data:
            raise HTTPException(status_code=500, detail="Error al crear pedido")

        order_id = order_result.data[0]["id"]

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
        supabase.table("order_items").insert(items_data).execute()  # tenant_filter:exempt:payload_includes_tenant_id

        response_body = {**order_result.data[0], "items": items_data}

        # Rev. 108 Fase B — COD: consumir stock inmediatamente (orden ya
        # está confirmed). Reusa el mismo path que auto_confirm + Wompi
        # APPROVED para mantener invariantes de stock.
        if order.payment_method == "cod":
            try:
                _decrement_stock_on_confirm(supabase, order_id, tenant_id)
                logger.info(
                    "Pedido COD %s creado confirmed + stock decrementado tenant=%s",
                    order_id, tenant_id,
                )
            except Exception as ce:
                logger.error(
                    "Error decrementando stock pedido COD %s: %s", order_id, ce,
                )

        # Confirmar de inmediato si el frontend lo solicita (Inbox flow)
        elif order.auto_confirm:
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
def get_order(
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
            # F19: .single() lanza APIError (PGRST116) en not-found → 500 genérico (el frontend no puede
            # distinguir not-found de error real). .limit(1) + unwrap devuelve el 404 correcto.
            .limit(1)
            .execute()
        )
        row = (result.data or [None])[0]
        if not row:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        return row
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener pedido")


@router.patch("/{order_id}", response_model=dict)
@audit_log(entity_type="order", action="updated")
def patch_order(
    order_id: str,
    patch: OrderPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    # F2 RBAC (business_call founder-aprobado): operator puede avanzar estado y
    # editar notas (opera el módulo), PERO cancelar un pedido dispara refund/void
    # de dinero → esa transición queda gateada a owner/manager (check inline abajo).
    role: str = Depends(get_current_role),
    # BLOQUE 0 (P1): PATCH es user-only (no dual-auth) y su transición cancel mueve
    # dinero → exige AAL2 si el operador tiene MFA. Step-up 1×/sesión (aal2 pasa directo).
    _mfa: None = Depends(enforce_mfa),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cambia estado y/o notas del pedido. owner/manager/operator (cancelar: solo
    owner/manager — mueve dinero).

    Lógica especial:
    - pending → confirmed: decrementa stock de cada variante de los ítems del pedido
      e inserta registros en stock_movements con reason='sale'.
    """
    if role not in {"owner", "manager", "operator"}:
        raise HTTPException(status_code=403, detail="Permiso insuficiente")
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

        # F2 RBAC: cancelar mueve dinero (refund/void Wompi) e inventario → solo
        # owner/manager. Operator opera el ciclo forward pero no cancela.
        if new_status == "cancelled" and role not in WRITE_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Solo owner o manager pueden cancelar un pedido (implica reembolso).",
            )

        # Verificar estado actual antes de actualizar
        current_result = (
            supabase.table("orders")
            .select("id, status")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not current_result or not current_result.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        current_status = current_result.data["status"]

        # A11 audit ORD-01: validar la TRANSICIÓN, no solo la pertenencia al set.
        if new_status and not _is_allowed_order_transition(current_status, new_status):
            raise HTTPException(
                status_code=409,
                detail=f"Transición de estado inválida: {current_status} → {new_status}",
            )

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
        # ── BLOQUE D item 4: reposición de stock al CANCELAR desde un estado ya
        #    decrementado (confirmed/processing/shipped). Antes patch_order (consola/API)
        #    sólo decrementaba al confirmar y NUNCA reponía al cancelar → inventario
        #    inflado permanente. Idempotente cross-path: mismo reason 'cancellation_refund'
        #    que el webhook MeLi (_restore_stock_for_meli_order) y el pipeline orchestrator
        #    (order_cancellation.py) → dos caminos de cancelación reponen una sola vez.
        elif new_status == "cancelled" and current_status in ("confirmed", "processing", "shipped"):
            _restore_stock_on_cancel(supabase, order_id, tenant_id)

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar pedido")


@router.post("/{order_id}/payment-link", response_model=dict)
@audit_log(entity_type="order", action="payment_link_created")
async def create_payment_link(
    order_id: str,
    request: Request,
    # A0.2c dual-auth (orchestrator → api)
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
    supabase: Client = Depends(get_service_client_internal_or_user),
    _role: str = Depends(require_write_internal_or_user),
    # BLOQUE 0 (P1): genera link de pago (money-movement). Dual-auth → guard
    # internal-aware: NO-OP para el bot (X-Internal-Service-Secret), AAL2 para operador.
    _mfa: None = Depends(enforce_mfa_internal_or_user),
):
    """
    Genera un link de pago Wompi para un pedido en estado pending o pending_payment.
    Persiste el link en la tabla payments y retorna la checkout_url.
    Válido por payment_link_ttl_minutes() minutos (env WOMPI_PAYMENT_LINK_TTL_MINUTES, default 30).
    """
    try:
        # F105: usar el wrapper resiliente (retry exponencial + circuit breaker) — cierra el riesgo P0
        # del dossier Wompi (un 5xx/timeout transitorio rompía el pago al primer intento). max_attempts=2
        # para no exceder el timeout ~20s del cliente orquestador (3×15s lo superaría → ReadTimeout).
        from integrations.wompi_client import create_payment_link_with_resilience as wompi_create_link
        from integrations.wompi_client import get_tenant_wompi_creds

        private_key, _, wompi_environment = get_tenant_wompi_creds(supabase, tenant_id)
        if not private_key:
            raise HTTPException(
                status_code=503,
                detail="Integración Wompi no configurada. Conéctala en Ajustes → Integraciones.",
            )

        order_res = (
            supabase.table("orders")
            .select(
                "id, status, total_amount, shipping_cost, notes, contact_id, "
                "contacts(name, phone, email, document_type, document_number)"
            )
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not order_res or not order_res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        order = order_res.data
        if order["status"] not in ("pending", "pending_payment"):
            raise HTTPException(
                status_code=409,
                detail=f"El pedido está en estado '{order['status']}' — solo se puede generar link para pedidos pending o pending_payment",
            )

        total_amount = float(order.get("total_amount") or 0)
        # BLOQUE A (P1): round, no int() — total_amount es numeric(10,2) leído como float;
        # total_amount*100 produce X.9999998 y int() trunca 1 cent (subcobro). round()
        # recupera los cents exactos acordados y alinea con payment_link_tool.py:438/485.
        amount_in_cents = int(round(total_amount * 100))

        if amount_in_cents < 150000:  # mínimo $1.500 COP para modelo Agregador
            raise HTTPException(
                status_code=422,
                detail=f"Monto mínimo Wompi es $1.500 COP. Monto actual: ${total_amount:,.0f}",
            )

        contact = order.get("contacts") or {}
        contact_name = contact.get("name") or "Cliente"
        short_id = order_id[:8].upper()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=payment_link_ttl_minutes())
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        link_data = await wompi_create_link(
            private_key=private_key,
            environment=wompi_environment,
            order_id=order_id,
            name=f"Pedido #{short_id} — {contact_name}"[:100],
            description=order.get("notes") or f"Pedido #{short_id}",
            amount_in_cents=amount_in_cents,
            expires_at=expires_at,
            contact=contact,  # rev. 68 — pre-popula customer_data
            max_attempts=2,   # F105: 2 intentos (retry solo errores donde Wompi NO creó el link)
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
        # F23: no filtrar {e} al cliente; se conserva la causa vía `from e` (como expenses.py).
        raise HTTPException(status_code=500, detail="Error al generar link de pago") from e


def _consume_cart_reservations_if_any(
    supabase: Client, order_id: str, tenant_id: str,
) -> int:
    """Si el pedido vino del flujo conversacional con soft-reserve activa,
    consume las reservas (decrementa stock + audita). Retorna el número de
    reservas consumidas. Si retorna 0, el caller debe usar el decrement
    directo (caso pedidos creados manualmente sin reservas previas).

    Diseño: orders→conversation_id→conversation_carts→stock_reservations.
    """
    try:
        # 1) Conversation_id del order (puede ser null en pedidos manuales)
        order_res = (
            supabase.table("orders")
            .select("conversation_id")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        conv_id = (order_res.data or {}).get("conversation_id")
        if not conv_id:
            return 0

        # 2) Cart abierto/checkout asociado a la conversación
        cart_res = (
            supabase.table("conversation_carts")
            .select("id")
            .eq("conversation_id", conv_id)
            .eq("tenant_id", tenant_id)
            .in_("status", ["open", "checkout"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        carts = cart_res.data or []
        if not carts:
            return 0
        cart_id = carts[0]["id"]

        # 3) Listar reservas activas del cart y consumirlas vía RPC
        res_list = (
            supabase.table("stock_reservations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        )
        reservation_ids = [r["id"] for r in (res_list.data or [])]
        consumed = 0
        for rid in reservation_ids:
            try:
                supabase.rpc(
                    "rpc_stock_reservation_consume",
                    # A11 IDOR (fase migrate-callers): p_tenant_id = tenant
                    # autenticado del request → el RPC filtra cross-tenant.
                    {"p_reservation_id": rid, "p_order_id": order_id, "p_tenant_id": tenant_id},
                ).execute()
                consumed += 1
            except Exception as exc:
                logger.warning(
                    "[STOCK] consume reservation=%s failed: %s", rid, exc,
                )
        # 4) Marcar cart como converted SIEMPRE que el order quede confirmed
        # (reservas son optimization opcional; ausencia no debe impedir el
        # cierre del cart). Rev. 103 — bug observado en pago real
        # (#A12E4D47): cart quedó status='open' tras Wompi webhook OK
        # porque el flow conversacional no crea stock_reservations
        # explícitamente (cart se llena vía cart_tool.add_item directo).
        # Resultado: panel del Inbox seguía mostrando "Carrito en
        # construcción" tras pago confirmado.
        try:
            supabase.table("conversation_carts").update({
                "status": "converted",
                "converted_order_id": order_id,
            }).eq("tenant_id", tenant_id).eq("id", cart_id).execute()
        except Exception as exc:
            logger.warning(
                "[CART] no pude marcar cart=%s converted tras order=%s: %s",
                cart_id, order_id, exc,
            )
        # Rev. 104 (F1-6) — emit `cart_events.order_confirmed` (best-effort).
        # Cross-service: duplicamos la inserción inline en lugar de importar
        # `cart.events.emit` (vive en ai-orchestrator) para mantener el
        # boundary de servicios. Schema canónico definido en migration
        # 20260510090000_cart_events.sql.
        try:
            supabase.table("cart_events").insert({
                "cart_id": cart_id,
                "tenant_id": tenant_id,
                "event_type": "order_confirmed",
                "event_payload": {"order_id": order_id, "consumed": consumed},
                "triggered_by": "webhook",
            }).execute()
        except Exception as exc:
            logger.debug(
                "[CART_EVENT] order_confirmed emit falló cart=%s: %s",
                cart_id, exc,
            )

        # Rev. 105 Sem 6 I.2.4 — consumir cupón aplicado (ADR-0015 D5).
        # Si el cart tenía cupón en status='applied', incrementamos
        # atómicamente coupons.redemptions_count y marcamos redemption
        # como 'consumed'. Best-effort — un fallo aquí NO bloquea el
        # cierre de orden.
        try:
            from lib.coupons import consume_redemption
            # Lookup cart row para obtener coupon_code (audit log payload).
            cart_meta = (
                supabase.table("conversation_carts")
                .select("coupon_id, coupon_code, discount_cents")
                .eq("tenant_id", tenant_id)
                .eq("id", cart_id)
                .single()
                .execute()
            )
            cart_meta_data = cart_meta.data or {}
            coupon_id_active = cart_meta_data.get("coupon_id")
            if coupon_id_active:
                consumed_coupon = consume_redemption(
                    supabase,
                    tenant_id=tenant_id,
                    cart_id=cart_id,
                    order_id=order_id,
                )
                if consumed_coupon:
                    # Emit cart_events.coupon_consumed (audit + telemetry).
                    try:
                        supabase.table("cart_events").insert({
                            "cart_id": cart_id,
                            "tenant_id": tenant_id,
                            "event_type": "coupon_consumed",
                            "event_payload": {
                                "coupon_id": coupon_id_active,
                                "code": cart_meta_data.get("coupon_code"),
                                "discount_cents": int(
                                    cart_meta_data.get("discount_cents") or 0
                                ),
                                "order_id": order_id,
                            },
                            "triggered_by": "webhook",
                        }).execute()
                    except Exception as exc:
                        logger.debug(
                            "[CART_EVENT] coupon_consumed emit falló: %s", exc,
                        )
                    logger.info(
                        "[COUPON] consumed via wompi_webhook order=%s cart=%s "
                        "coupon=%s",
                        order_id, cart_id, cart_meta_data.get("coupon_code"),
                    )
        except Exception as exc:
            logger.warning(
                "[COUPON] consume_redemption error order=%s cart=%s: %s "
                "(no bloquea cierre orden)",
                order_id, cart_id, exc,
            )

        return consumed
    except Exception as exc:
        logger.warning("[STOCK] reservations consume probe failed: %s", exc)
        return 0


def _fire_meli_sync_for_order(supabase: Client, order_id: str, tenant_id: str) -> None:
    """F4 — empuja a MeLi el stock actualizado de las variantes de una orden tras
    consumir reservas (flujo bot WhatsApp). El path de decremento directo ya
    sincroniza inline; el consume de reservas NO lo hacía → MeLi mostraba stock
    viejo tras una venta por WhatsApp (oversell cross-canal). sync_meli_stock es
    no-op si la variante no tiene listing MeLi activo (guardado)."""
    try:
        items = (
            supabase.table("order_items")
            .select("variation_id")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[STOCK] MeLi sync: lookup order_items falló order=%s: %s", order_id, exc)
        return
    seen: set = set()
    for it in items:
        var_id = it.get("variation_id")
        if not var_id or var_id in seen:
            continue
        seen.add(var_id)
        try:
            vr = (
                supabase.table("product_variations")
                .select("stock_quantity")
                .eq("id", var_id).eq("tenant_id", tenant_id).single().execute()
            )
            new_stock = (vr.data or {}).get("stock_quantity")
            if new_stock is None:
                continue
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(sync_meli_stock(var_id, new_stock, supabase))
            except RuntimeError:
                try:
                    asyncio.run(sync_meli_stock(var_id, new_stock, supabase))
                except Exception as meli_err:
                    logger.warning(
                        "[STOCK] Sync MeLi falló variation=%s (no bloquea): %s", var_id, meli_err,
                    )
        except Exception as exc:
            logger.warning("[STOCK] MeLi sync: variation=%s falló: %s", var_id, exc)


def _decrement_stock_on_confirm(supabase: Client, order_id: str, tenant_id: str) -> None:
    """
    Decrementa stock de las variantes incluidas en el pedido al confirmarlo.
    Inserta registros en stock_movements para auditoría.
    Si una variante no tiene suficiente stock, se decrementa igualmente
    (permitir negativo — el operador verá el alerta de bajo stock).

    Si el pedido tiene reservas activas (flujo conversacional con
    soft-reserve), las consume vía RPC en lugar de decremento directo
    para evitar doble descuento. Si no hay reservas, sigue el path viejo.
    """
    consumed_reservations = _consume_cart_reservations_if_any(
        supabase, order_id, tenant_id,
    )
    if consumed_reservations > 0:
        logger.info(
            "[STOCK] orden %s consumió %d reservas activas — skip decrement directo",
            order_id, consumed_reservations,
        )
        # F4: el consume de reservas ya decrementó stock (vía RPC) pero NO sincronizaba
        # MeLi → sincronizar aquí también (el path directo de abajo ya lo hace inline).
        _fire_meli_sync_for_order(supabase, order_id, tenant_id)
        return

    try:
        items_result = (
            supabase.table("order_items")
            .select("variation_id, quantity")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        items = items_result.data or []

        # BLOQUE C item 4: AGREGAR por variation_id ANTES de decrementar. La idempotencia del
        # RPC es por (order_id, variation_id, 'sale'); dos líneas de order_items de la MISMA
        # variante colapsarían al mismo key → la 2ª sería no-op y se perdería su qty. Sumamos
        # las cantidades por variante para hacer UNA sola llamada de decremento por variante.
        agg: dict = {}
        for item in items:
            _vid = item.get("variation_id")
            _qty = item.get("quantity", 0) or 0
            if not _vid or _qty <= 0:
                continue
            agg[_vid] = agg.get(_vid, 0) + int(_qty)

        for variation_id, quantity in agg.items():
            # BLOQUE C item 4: decremento ATÓMICO e IDEMPOTENTE vía RPC. El INSERT del
            # movement (ON CONFLICT order_id,variation_id,reason DO NOTHING) actúa de guard:
            # un retry Wompi tardío / webhook duplicado sobre la misma (orden,variante,'sale')
            # es NO-OP (no re-decrementa) → cierra el doble-decremento. Reemplaza el
            # read-modify-write en 3 llamadas separadas (no atómico, race-prone) previo.
            try:
                _rpc = supabase.rpc("rpc_stock_decrement", {
                    "p_tenant_id": tenant_id,
                    "p_variation_id": variation_id,
                    "p_qty": int(quantity),
                    "p_order_id": order_id,
                    "p_reason": "sale",
                }).execute()
                new_stock = _rpc.data if isinstance(_rpc.data, int) else None
            except Exception as _dec_exc:
                logger.error(
                    "[STOCK] rpc_stock_decrement falló order=%s var=%s: %s",
                    order_id, variation_id, _dec_exc,
                )
                continue
            if new_stock is None:
                continue

            # Sync stock a MeLi si hay listing activo vinculado.
            # Se invoca desde context sync (background task del webhook Wompi).
            # asyncio.ensure_future requiere un event loop activo — si no está,
            # programar la tarea sin bloquear el decrement de los demás items.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(sync_meli_stock(variation_id, new_stock, supabase))
            except RuntimeError:
                # Sin event loop activo (background sync) — ejecutar fire-and-forget
                # en un nuevo loop dedicado, sin bloquear el resto del decrement.
                try:
                    asyncio.run(sync_meli_stock(variation_id, new_stock, supabase))
                except Exception as meli_err:
                    logger.warning(
                        "[STOCK] Sync MeLi falló para variation=%s (no bloquea decrement): %s",
                        variation_id, meli_err,
                    )

    except Exception as e:
        # No fallar la confirmación del pedido si el stock no se puede decrementar
        logger.error(
            "Error decrementando stock para pedido %s: %s",
            order_id, e
        )


def _restore_stock_on_cancel(supabase: Client, order_id: str, tenant_id: str) -> None:
    """Repone stock de las variantes de un pedido al CANCELARLO desde la consola/API.

    BLOQUE D item 4: patch_order sólo decrementaba al confirmar y NUNCA reponía al
    cancelar → inventario inflado permanente cuando un operador cancela un pedido ya
    confirmado. Repone SÓLO lo realmente decrementado leyendo los movimientos
    'sale'/'reservation_consumed' de la orden (no la qty de order_items, que puede
    diferir del delta clampeado por over-sell). Idempotente por
    (order_id, variation_id, 'cancellation_refund') vía el índice único — mismo reason
    que el webhook MeLi (_restore_stock_for_meli_order) y el pipeline orchestrator
    (order_cancellation.py) → dos caminos de cancelación reponen una sola vez.
    """
    try:
        movements = (
            supabase.table("stock_movements")
            .select("variation_id, delta")
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id)
            .in_("reason", ["sale", "reservation_consumed"])
            .execute()
        ).data or []
        restore_by_var: dict = {}
        for mv in movements:
            vid = mv.get("variation_id")
            qty = abs(int(mv.get("delta") or 0))
            if vid and qty > 0:
                restore_by_var[vid] = restore_by_var.get(vid, 0) + qty

        for variation_id, qty in restore_by_var.items():
            try:
                _rpc = supabase.rpc("rpc_stock_restore", {
                    "p_tenant_id": tenant_id,
                    "p_variation_id": variation_id,
                    "p_qty": int(qty),
                    "p_order_id": order_id,
                    "p_reason": "cancellation_refund",
                }).execute()
                new_stock = _rpc.data if isinstance(_rpc.data, int) else None
            except Exception as _res_exc:
                logger.error(
                    "[STOCK] rpc_stock_restore falló order=%s var=%s: %s",
                    order_id, variation_id, _res_exc,
                )
                continue
            if new_stock is None:
                continue

            # Sync a MeLi (loop-aware, igual patrón que el decremento).
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(sync_meli_stock(variation_id, new_stock, supabase))
            except RuntimeError:
                try:
                    asyncio.run(sync_meli_stock(variation_id, new_stock, supabase))
                except Exception as meli_err:
                    logger.warning(
                        "[STOCK] Sync MeLi (restore) falló variation=%s (no bloquea): %s",
                        variation_id, meli_err,
                    )

    except Exception as e:
        logger.error("Error reponiendo stock (cancel) para pedido %s: %s", order_id, e)


@router.post("/{order_id}/generate-shipping-guide", response_model=dict)
async def generate_shipping_guide_endpoint(
    order_id: str,
    # A0.2c dual-auth (orchestrator → api)
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
    supabase: Client = Depends(get_service_client_internal_or_user),
    role: str = Depends(get_role_internal_or_user),
    # Ola 0 — genera guía REAL (Aveonline cobra = movimiento de dinero) → exige MFA
    # AAL2 al operador. internal_or_user hace NO-OP a la llamada del bot/orchestrator.
    _mfa: None = Depends(enforce_mfa_internal_or_user),
):
    """Genera guía Aveonline para una orden — manual desde Inbox.

    Rev. 108 Fase B. Aplica especialmente para órdenes COD (que NO disparan
    el flujo wompi_webhook → guía auto). El operador en Inbox aprieta botón
    "Generar guía" y este endpoint:
      1. Valida orden existe + estado confirmed/pending
      2. Llama `_generate_shipping_guide` (reusa lógica wompi_webhook)
      3. Si OK, dispara etapa 2 WhatsApp + email "Guía asignada"
      4. Retorna shipment row con tracking_number + label_url

    Idempotente: si ya hay shipment con tracking_number para este order_id,
    retorna esa info sin re-generar.

    Permisos: owner + manager (no operator — genera costos reales).
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            403, "Solo owner o manager pueden generar guías de envío",
        )

    # Lookup orden + payment_method
    order_res = (
        supabase.table("orders")
        .select("id, status, payment_method, conversation_id, contact_id")
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    order = order_res.data if order_res else None
    if not order:
        raise HTTPException(404, "Pedido no encontrado")

    if order["status"] not in ("pending", "pending_payment", "confirmed"):
        raise HTTPException(
            422,
            f"No se puede generar guía para pedido en estado '{order['status']}'",
        )

    # Idempotencia: ¿ya hay shipment con tracking?
    existing = (
        supabase.table("shipments")
        .select("id, tracking_number, label_url, tracking_url, carrier, status")
        .eq("order_id", order_id)
        .eq("tenant_id", tenant_id)
        .limit(1).execute()
    )
    if existing.data:
        row = existing.data[0]
        if row.get("tracking_number"):
            logger.info(
                "[ORDERS][GEN_GUIDE] orden=%s ya tiene shipment con tracking=%s — idempotente",
                order_id[:8], row["tracking_number"],
            )
            return {
                "ok": True,
                "idempotent": True,
                "shipment": row,
            }

    # Invocar lógica compartida con wompi_webhook.
    # Rev. 108 fix arquitectónico — usamos versión async directa
    # (`_generate_shipping_guide_async`) porque este endpoint corre en
    # context async FastAPI. La versión sync wrapper (asyncio.run)
    # rompería el event loop existente.
    from routers.wompi_webhook import (
        _generate_shipping_guide_async,
        _notify_client_shipment_label_ready,
        _send_payment_confirmation_email,
    )

    try:
        ok = await _generate_shipping_guide_async(
            supabase, order_id=order_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "[ORDERS][GEN_GUIDE] _generate_shipping_guide raise order=%s: %s",
            order_id, exc,
        )
        raise HTTPException(502, f"Error al llamar Aveonline: {exc}")

    if not ok:
        # Skip o fail — recuperar shipment pending si existe
        return {
            "ok": False,
            "error": (
                "No se pudo generar la guía. Revisa configuración Aveonline "
                "(carrier, dirección destino, contrato). Detalle en logs."
            ),
        }

    # Disparar etapa 2 notifs (igual que wompi_webhook OK path)
    try:
        sh = (
            supabase.table("shipments")
            .select("carrier, tracking_number, tracking_url")
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id).limit(1).execute()
        )
        sh_row = (sh.data or [{}])[0]
        conv_id = order.get("conversation_id")
        if conv_id and sh_row.get("tracking_number"):
            _notify_client_shipment_label_ready(
                supabase,
                conversation_id=conv_id,
                tenant_id=tenant_id,
                order_id=order_id,
                carrier=sh_row.get("carrier") or "",
                tracking_number=sh_row.get("tracking_number") or "",
                tracking_url=sh_row.get("tracking_url") or "",
            )
        _send_payment_confirmation_email(
            supabase=supabase, order_id=order_id, tenant_id=tenant_id,
            template_mode="shipment_label_ready",
        )
    except Exception as exc:
        logger.warning(
            "[ORDERS][GEN_GUIDE] notifs etapa 2 fallaron order=%s: %s",
            order_id, exc,
        )

    final = (
        supabase.table("shipments")
        .select("id, tracking_number, label_url, tracking_url, carrier, status")
        .eq("tenant_id", tenant_id)
        .eq("order_id", order_id)
        .limit(1).execute()
    )
    return {
        "ok": True,
        "idempotent": False,
        "shipment": (final.data or [{}])[0],
    }
