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
    get_current_user_id,
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
from routers.marketplace import sync_meli_stock

# ── Capa de dominio compartida (Track 5 M2.1) ────────────────────────────────
# La lógica de negocio de pedidos vive en `konvi_domain.orders` (paquete
# packages/shared-py — única fuente). Este router es el ADAPTADOR HTTP:
# dual-auth, RBAC/MFA, Idempotency-Key, audit decorator y DomainError→HTTP.
from konvi_domain import Actor, Channel, DomainError, ErrorCode, Role
from konvi_domain.orders import payments as payments_service  # M2.3
from konvi_domain.orders import service as orders_service
from konvi_domain.orders import (
    VALID_STATUSES,
    CreateOrderInput,
    OrderItemInput,
)

# La máquina de estados (A11 audit ORD-01: forward-only + cancelar desde
# no-terminal + idempotente; terminal no reabrible) tiene UNA fuente en el
# paquete — se conserva el alias con el nombre histórico (lo usan patch_order
# y tests/test_a11_order_state_machine.py).
from konvi_domain.orders import is_allowed_order_transition as _is_allowed_order_transition

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])


# TTL de validez del link Wompi: ÚNICA fuente `konvi_domain.orders.payments`
# (M2.3 — política reuso/TTL colapsada router↔bot; el shim
# `integrations.wompi_client` la re-exporta para wompi_webhook.py). Espejos
# congelados del bot (payment_link_tool, PAYMENT_REMINDER_DELAY_MINUTES):
# ver el docstring de `konvi_domain/orders/payments.py` y ADR-0011.


# ── Adaptador HTTP ↔ capa de dominio (M2.1) ──────────────────────────────────

_DOMAIN_ERROR_HTTP = {
    ErrorCode.VALIDATION: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PRECONDITION: 409,
    ErrorCode.UPSTREAM: 500,
    ErrorCode.TENANT_MISMATCH: 403,
}


def _domain_error_to_http(exc: DomainError) -> HTTPException:
    """Mapeo único DomainError → HTTPException (mismos status/detalle heredados).

    `exc.http_status` (M2.3) overridea el mapeo cuando el dominio conoce el
    status exacto heredado (p.ej. proveedor no configurado → 503, no 500)."""
    return HTTPException(
        status_code=exc.http_status or _DOMAIN_ERROR_HTTP.get(exc.code, 500),
        detail=exc.message,
    )


def _build_actor(request: Request, tenant_id: str, role: Optional[str]) -> Actor:
    """Actor del contrato desde el borde HTTP (dual-auth).

    Canal: header X-Internal-Service-Secret presente → BOT (orchestrator→API);
    si no, CONSOLE (JWT usuario). Rol: el verificado por la dependency; None en
    lecturas tenant-scoped que no verifican rol (patrón heredado list_claims).
    """
    channel = Channel.BOT if request.headers.get("X-Internal-Service-Secret") else Channel.CONSOLE
    return Actor(channel=channel, tenant_id=tenant_id, role=Role(role) if role else None)


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

        # ── Dominio en la capa compartida (Track 5 M2.1) ─────────────────────
        # Toda la lógica de negocio (total recomputado + herencia de cupón vivo
        # del cart, validación FKs anti-IDOR, estados iniciales credit/cod,
        # insert + adopt-winner 23505, efectos de stock COD/auto-confirm) vive en
        # konvi_domain.orders.service.create_order — única fuente consumida por
        # este adaptador HTTP y (en M3) por el canal bot. Los invariantes de
        # dinero se preservan EXACTOS (tests/test_orders_channel_parity.py).
        input_ = CreateOrderInput(
            items=tuple(
                OrderItemInput(
                    product_id=i.product_id,
                    variation_id=i.variation_id,
                    title=i.title,
                    unit_price=i.unit_price,
                    unit_cost=i.unit_cost,
                    quantity=i.quantity,
                )
                for i in order.items
            ),
            contact_id=order.contact_id,
            conversation_id=order.conversation_id,
            notes=order.notes,
            shipping_cost=order.shipping_cost,
            auto_confirm=order.auto_confirm,
            payment_link=order.payment_link,
            payment_method=order.payment_method,
        )
        try:
            result = orders_service.create_order(
                supabase,
                tenant_id=tenant_id,
                input=input_,
                actor=_build_actor(request, tenant_id, _role),
                # El efecto de stock al confirmar queda en ESTE servicio (acoplado
                # a sync_meli_stock) hasta InventoryService (backlog M1 #3) —
                # entonces solo cambia la implementación inyectada.
                on_confirm_stock=_decrement_stock_on_confirm,
            )
        except DomainError as de:
            raise _domain_error_to_http(de)

        body = result.body()
        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=result.http_status,
            body=body,
        )
        if result.adopted_existing:
            # Carrera 23505 adoptada (B1): la respuesta emitida/guardada es 200.
            return JSONResponse(status_code=200, content=body)
        return body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error creando pedido tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear pedido")


@router.get("/", response_model=dict)
def list_orders(
    request: Request,
    status: Optional[str] = None,
    contact_id: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista pedidos del tenant (filtros estado/contacto/búsqueda + paginación
    + conteos por estado). Cierra el hueco M1 §H2 (la consola listaba directo
    de PostgREST). La lógica vive en konvi_domain.orders.service.list_orders."""
    if page < 1:
        raise HTTPException(status_code=422, detail="page debe ser ≥ 1")
    if not 1 <= per_page <= 100:
        raise HTTPException(status_code=422, detail="per_page debe estar entre 1 y 100")
    status_filter = None
    if status and status != "all":
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Estado inválido. Válidos: {', '.join(sorted(VALID_STATUSES))}",
            )
        status_filter = status
    try:
        page_res = orders_service.list_orders(
            supabase,
            tenant_id=tenant_id,
            actor=_build_actor(request, tenant_id, None),
            status=status_filter,
            contact_id=contact_id,
            q=q,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return {
            "orders": page_res.orders,
            "total": page_res.total,
            "counts": page_res.counts,
            "page": page,
            "per_page": per_page,
        }
    except DomainError as de:
        raise _domain_error_to_http(de)
    except Exception as e:
        logger.error("Error listando pedidos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al listar pedidos")


@router.get("/{order_id}", response_model=dict)
def get_order(
    order_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Detalle del pedido con ítems y datos del contacto (konvi_domain M2.1)."""
    try:
        return orders_service.get_order(
            supabase,
            tenant_id=tenant_id,
            order_id=order_id,
            actor=_build_actor(request, tenant_id, None),
        )
    except DomainError as de:
        raise _domain_error_to_http(de)
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
    _user_id: Optional[str] = Depends(get_current_user_id),
):
    """
    Cambia estado y/o notas del pedido. owner/manager/operator (cancelar: solo
    owner/manager — mueve dinero).

    Lógica especial:
    - pending → confirmed: decrementa stock de cada variante de los ítems del pedido
      e inserta registros en stock_movements con reason='sale'.
    - → cancelled (M2.2): delega al pipeline legal unificado
      `konvi_domain.orders.cancellation` — misma semántica que el bot (triage,
      audit order_cancellations, void Wompi, cancel guía, restock idempotente,
      notificaciones). Antes la consola hacía flip + restock "a medias".
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

        # ── M2.2: cancelar delega al pipeline legal unificado ────────────────
        # (konvi_domain.orders.cancellation) — UNA semántica para consola y bot:
        # triage de riesgo (registrado en auditoría para staff), audit SIC
        # order_cancellations, void Wompi automático en ventana, cancel de guía
        # Aveonline, restock idempotente (reservas + movements), notificación al
        # cliente por WhatsApp y al operador por Telegram si el refund es manual.
        if new_status == "cancelled":
            # Notas del operador (si vienen) quedan en la orden antes de cancelar.
            if "notes" in data:
                (
                    supabase.table("orders")
                    .update({"notes": data["notes"]})
                    .eq("id", order_id)
                    .eq("tenant_id", tenant_id)
                    .execute()
                )
            return _cancel_via_domain_pipeline(
                supabase, order_id=order_id, tenant_id=tenant_id,
                user_id=_user_id, request=request, reason_text=data.get("notes") or "",
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

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando pedido %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar pedido")


def _cancel_via_domain_pipeline(
    supabase: Client, *, order_id: str, tenant_id: str,
    user_id: Optional[str], request: Request, reason_text: str,
) -> dict:
    """Adaptador consola → `konvi_domain.orders.cancellation.cancel_order` (M2.2).

    Mapea CancellationResult a la respuesta HTTP: 404 si la orden no existe,
    409 defensivo si el pipeline escala (no ocurre para staff — la escalación
    bloquea solo al canal customer), 200 con la orden re-leída + resumen de la
    cancelación. Efectos de proveedor inyectados (puertos del servicio API).
    """
    from konvi_domain.orders.cancellation import CancellationRequest as _CancelReq
    from konvi_domain.orders.cancellation import cancel_order as _domain_cancel

    from lib.order_cancel_ports import (
        build_api_cancellation_ports,
        send_cancellation_notifications,
    )

    cancel_result = asyncio.run(_domain_cancel(
        supabase,
        _CancelReq(
            order_id=order_id,
            tenant_id=tenant_id,
            # Enum DB order_cancellation_actor: 'operator' cubre staff de
            # consola (owner/manager); la granularidad del rol queda en
            # cancelled_by_user_id + audit_log. ("owner" rompe el enum 22P02 —
            # destapado por la certificación live M2.2.)
            actor="operator",
            reason_code="operator_console",
            reason_text=reason_text,
            user_id=user_id,
            ip_address=request.client.host if request and request.client else None,
        ),
        ports=build_api_cancellation_ports(supabase),
    ))

    if not cancel_result.success:
        if cancel_result.requires_escalation:
            raise HTTPException(
                status_code=409,
                detail="La cancelación requiere revisión: "
                       + ", ".join(cancel_result.escalation_reasons),
            )
        logger.error(
            "[CANCEL] pipeline falló order=%s: %s", order_id, cancel_result.error,
        )
        raise HTTPException(status_code=500, detail="Error al cancelar el pedido")

    # Re-leer la orden ya cancelada por el pipeline (mismo shape que el PATCH
    # heredado: la fila actualizada + resumen de la cancelación para la UI).
    row = (
        supabase.table("orders")
        .select("*")
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    order_row = (row.data if row else None) or {}

    send_cancellation_notifications(
        supabase,
        result=cancel_result,
        tenant_id=tenant_id,
        conversation_id=order_row.get("conversation_id"),
    )

    return {
        **order_row,
        "cancellation": {
            "id": cancel_result.cancellation_id,
            "status": cancel_result.status,
            "refund_method": cancel_result.refund_method,
            "refund_status": cancel_result.refund_status,
            "refund_amount_cents": cancel_result.refund_amount_cents,
        },
    }


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
    # G3 audit: money-movement sin rate-limit → un retry storm del bot u
    # operador podía martillear Wompi. Mismo bucket write.default que
    # create_order/patch_order (parámetro, patrón de este archivo).
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Genera un link de pago Wompi para un pedido en estado pending o pending_payment.
    Persiste el link en la tabla payments y retorna la checkout_url.
    Válido por payment_link_ttl_minutes() minutos (env WOMPI_PAYMENT_LINK_TTL_MINUTES, default 30).
    Si la orden ya tiene un link vigente (payments pending dentro del TTL), lo
    REUSA: responde con ese link sin llamar a Wompi ni insertar fila nueva.
    """
    idem_session = None
    try:
        # G3 follow-up: Idempotency-Key (mismo patrón que create_order). El
        # reuso por TTL cubre la doble-ejecución dentro de la ventana de 30 min;
        # la key cubre el retry exacto (replay de la MISMA respuesta guardada).
        request_hash = payload_fingerprint({"order_id": order_id, "route": "payment-link"})
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

        # ── M2.3: la operación de dominio vive en el paquete compartido ──────
        # (konvi_domain.orders.payments.get_or_create_payment_link) — UNA
        # política de reuso/TTL para todos los canales (colapsa el espejo
        # router↔bot medido en M1 §3.3; el bot conserva el suyo congelado
        # hasta B-2/M3, defendido por tests/test_payment_link_policy_parity.py).
        # El orden de pasos heredado (creds→orden→status→reuso→monto→crear→
        # insert→flip) y los mensajes/status exactos los garantiza el servicio;
        # aquí solo se traduce DomainError → HTTPException.
        from lib.order_payment_ports import build_api_payment_ports

        try:
            outcome = await payments_service.get_or_create_payment_link(
                supabase,
                tenant_id=tenant_id,
                order_id=order_id,
                actor=_build_actor(request, tenant_id, _role),
                ports=build_api_payment_ports(supabase),
            )
        except DomainError as de:
            raise _domain_error_to_http(de) from de

        body = outcome.body()
        finalize_idempotency(
            supabase=supabase, tenant_id=tenant_id, session=idem_session,
            status_code=200, body=body,
        )
        return body

    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
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
