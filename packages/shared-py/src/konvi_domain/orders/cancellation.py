"""Pipeline unificado de cancelación de pedidos (Track 5 M2.2).

Ley 1480 de 2011 (Estatuto del Consumidor). UNA semántica para todos los canales
— extraído intacto de `services/ai-orchestrator/lib/order_cancellation.py`
(pipeline production-grade del bot), con los efectos de proveedor INYECTADOS
como puertos para que cada canal cablee los suyos:

  - Consola (API): void vía `integrations/wompi_client` + cancel guía vía
    `integrations/aveonline_client` + notificaciones vía `lib/operator_alerts`
    y `lib/client_notifications`.
  - Bot: conserva su copia congelada hasta el bloque bot (B-2 lo adopta del
    paquete; la paridad de outcome la certifica
    `tests/test_cancellation_outcome_parity.py`).

Regla de canal única y deliberada: la **escalación triage bloquea solo al actor
`customer`** (el bot autónomo DEBE diferir a un humano). Un miembro del equipo
(owner/manager/operator) ES el humano — el pipeline procede y REGISTRA las
razones de riesgo en la fila de auditoría (`escalation_reason`), sin bloquear.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

# Única fuente de los plazos legales (antes escrita a mano en 4 sitios).
from konvi_domain.legal import REEMBOLSO_DIAS_CALENDARIO_MAX, dias_reembolso

logger = logging.getLogger("konvi_domain.orders.cancellation")


# ── Escalation rules ─────────────────────────────────────────────────────────
# Cuando el BOT (actor customer) DEBE NO ejecutar autónomo y escalar a operador.

ESCALATION_REASONS = {
    "ORDER_IN_TRANSIT":        "Orden ya recogida por courier — flow RMA aplica",
    "ORDER_DELIVERED":         "Orden entregada — flow retracto Art. 47 aplica",
    "HIGH_VALUE":              "Monto excede threshold tenant",
    "PRODUCT_DEFECT_CLAIMED":  "Cliente menciona producto defectuoso → reclamo garantía",
    "MISSING_PACKAGE":         "Cliente menciona no haber recibido → disputa courier",
    "PAYMENT_DISPUTE":         "Cliente menciona disputa pago → riesgo legal",
    "MULTIPLE_PENDING_ORDERS": "Cliente tiene 2+ pedidos activos, requiere selección",
    "REFUND_TO_OTHER_ACCOUNT": "Cliente solicita refund a cuenta distinta → fraude potencial",
    "DISCOUNT_REQUEST":        "Cliente pide cancel + descuento futuro → upsell humano",
    "VOID_API_FAILURE":        "Wompi void falló con error no transitorio",
    "AVEONLINE_CANCEL_FAILURE": "Aveonline cancelarGuia falló → coordinación manual courier",
    "WOMPI_RACE_CONDITION":    "APPROVED tardío durante cancel → review manual",
    "CUSTOMER_HOSTILE":        "Sentiment hostile → mejor atención humana",
    "REPEAT_CANCELLATION":     "Cliente con patrón cancelaciones repetidas → review",
    "POLICY_DISABLED":         "Política tenant prohíbe cancel automático para este caso",
}


@dataclass
class CancellationItem:
    """Item específico a cancelar (cancelación parcial)."""
    cart_item_id: str
    product_id: str
    variation_id: str
    qty: int
    unit_price_cents: int


@dataclass
class CancellationRequest:
    """Input al pipeline."""
    order_id: str
    tenant_id: str
    actor: str  # enum DB order_cancellation_actor: 'customer' | 'operator' (consola) | 'system_auto' | 'system_fraud'
    reason_code: str = "customer_request"
    reason_text: str = ""
    items: Optional[list[CancellationItem]] = None  # None = cancelación total
    user_id: Optional[str] = None  # si el actor es staff (auditoría)
    ip_address: Optional[str] = None
    conversation_id: Optional[str] = None


@dataclass
class CancellationResult:
    """Output del pipeline."""
    success: bool
    cancellation_id: Optional[str] = None
    status: str = "pending"  # pending | completed | partial_failure | failed
    requires_escalation: bool = False
    escalation_reasons: list[str] = field(default_factory=list)
    refund_amount_cents: int = 0
    refund_method: Optional[str] = None
    refund_status: str = "not_applicable"
    customer_message: str = ""  # mensaje natural para enviar al cliente
    operator_notification: str = ""  # mensaje para Telegram operador
    error: Optional[str] = None


@dataclass(frozen=True)
class CancellationPorts:
    """Efectos de proveedor inyectados por el adaptador del canal.

    - `void_credentials(tenant_id) -> (private_key, environment) | None`:
      credenciales Wompi del tenant (Vault). None = sin llave → refund manual.
    - `void_payment(private_key, environment, txn_id) -> None`: ejecuta el
      void Wompi. Lanza excepción en falla.
    - `cancel_shipping_guide(tenant_id, tracking_number) -> {"ok", "method"}`:
      cancela la guía en el carrier (async). None = sin soporte → manual.
    Si los puertos de void son None = el canal no soporta auto-void
    (equivalente al import-failure del bot) → refund manual.

    - `on_stock_restored(variation_id, new_stock) -> None`: hook por variante
      repuesta (la consola sincroniza MeLi — `_fire_meli_sync`; el bot lo gana
      cuando adopte el paquete en B-2). None = sin efecto extra.
    """
    void_credentials: Optional[Callable[[str], Optional[tuple[str, str]]]] = None
    void_payment: Optional[Callable[[str, str, str], None]] = None
    cancel_shipping_guide: Optional[Callable[[str, str], Awaitable[dict]]] = None
    on_stock_restored: Optional[Callable[[str, int], None]] = None


# ── Policy ───────────────────────────────────────────────────────────────────

@dataclass
class TenantPolicy:
    allow_cancel_after_picked_up: bool = False
    auto_void_card_window_hours: int = 23
    # Techo legal en comercio electrónico: 15 días CALENDARIO (Ley 1480 art. 47,
    # mod. art. 3 Ley 2439 de 2024). El default era 30 —el plazo del comercio
    # presencial— y de ahí salía el mensaje al operador y al cliente.
    manual_refund_legal_days: int = REEMBOLSO_DIAS_CALENDARIO_MAX
    allow_partial_cancellation: bool = True
    enable_retracto_flow: bool = True
    retracto_window_business_days: int = 5
    retracto_return_paid_by: str = "customer"
    retracto_excluded_product_ids: list = field(default_factory=list)
    retracto_excluded_categories: list = field(default_factory=list)
    high_value_escalation_threshold_cents: int = 50000000  # $500K
    escalate_card_voids: bool = False

    def __post_init__(self) -> None:
        """El techo legal se aplica ACÁ y no solo al leer de la base: la defensa
        tiene que estar en el tipo, no en un camino."""
        if self.manual_refund_legal_days > REEMBOLSO_DIAS_CALENDARIO_MAX:
            self.manual_refund_legal_days = REEMBOLSO_DIAS_CALENDARIO_MAX
        if self.manual_refund_legal_days < 1:
            self.manual_refund_legal_days = REEMBOLSO_DIAS_CALENDARIO_MAX


def load_policy(supabase: Any, tenant_id: str) -> TenantPolicy:
    try:
        row = (
            supabase.table("tenant_cancellation_policy")
            .select("*")
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        ).data or {}
    except Exception:
        row = {}
    return TenantPolicy(
        allow_cancel_after_picked_up=bool(row.get("allow_cancel_after_picked_up", False)),
        auto_void_card_window_hours=int(row.get("auto_void_card_window_hours") or 23),
        # `dias_reembolso` aplica el techo legal — una fila vieja o un default
        # olvidado no pueden volver a prometer un plazo que la ley no permite.
        manual_refund_legal_days=dias_reembolso(row),
        allow_partial_cancellation=bool(row.get("allow_partial_cancellation", True)),
        enable_retracto_flow=bool(row.get("enable_retracto_flow", True)),
        retracto_window_business_days=int(row.get("retracto_window_business_days") or 5),
        retracto_return_paid_by=str(row.get("retracto_return_paid_by") or "customer"),
        retracto_excluded_product_ids=list(row.get("retracto_excluded_product_ids") or []),
        retracto_excluded_categories=list(row.get("retracto_excluded_categories") or []),
        high_value_escalation_threshold_cents=int(
            row.get("high_value_escalation_threshold_cents") or 50000000),
        escalate_card_voids=bool(row.get("escalate_card_voids", False)),
    )


# ── Void eligibility (regla pura de dominio — dossier Wompi H.3.2) ───────────

def is_void_eligible(payment_method_type: str, paid_at_iso: Optional[str]) -> bool:
    """Heurística pre-call: ¿este pago es elegible para void?

    Reglas: método CARD (Visa/Mastercard/Amex) + captura < 24h (ventana de
    settlement típica). NO es garantía — Wompi puede rechazar igual; sirve como
    GATE PRE-CALL para evitar 422 cuando ya sabemos que no aplica.
    `paid_at_iso` None o no parseable = optimista (intentamos).
    """
    if (payment_method_type or "").upper() != "CARD":
        return False
    if not paid_at_iso:
        return True
    try:
        paid_at = datetime.fromisoformat(paid_at_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Ventana conservadora 23h para no llegar al borde de settlement.
        return (now - paid_at) < timedelta(hours=23)
    except Exception:
        return True


# ── Escalation triage ────────────────────────────────────────────────────────

def detect_escalation_reasons(
    *,
    order: dict,
    request: CancellationRequest,
    policy: TenantPolicy,
    shipment: Optional[dict] = None,
    payment: Optional[dict] = None,
) -> list[str]:
    """Evalúa las reglas de escalación. Vacía = autónomo OK (canal customer)."""
    reasons: list[str] = []

    # E1: orden en tránsito o entregada
    order_status = (order.get("status") or "").lower()
    if order_status in {"delivered", "shipped"}:
        reasons.append("ORDER_DELIVERED")
    elif shipment and (shipment.get("status") or "").lower() in {
        "picked_up", "in_transit", "out_for_delivery",
    }:
        if not policy.allow_cancel_after_picked_up:
            reasons.append("ORDER_IN_TRANSIT")

    # E2: alto monto
    total_cents = int((order.get("total_amount") or 0) * 100)
    if total_cents > policy.high_value_escalation_threshold_cents:
        reasons.append("HIGH_VALUE")

    # E3: cliente menciona defectuoso (reclamo garantía, no cancel)
    rtext = (request.reason_text or "").lower()
    if any(w in rtext for w in [
        "defectuos", "dañad", "roto", "mal estado", "no funciona",
        "vino mal", "calidad mala",
    ]):
        reasons.append("PRODUCT_DEFECT_CLAIMED")

    # E4: cliente menciona no recibido (disputa courier)
    if any(w in rtext for w in [
        "no me lleg", "no ha llegado", "no me ha llegado",
        "no me ha llegada", "extraviad", "perdid", "robad",
        "nunca recibí", "nunca lleg",
    ]):
        reasons.append("MISSING_PACKAGE")

    # E5: cliente menciona disputa pago
    if any(w in rtext for w in [
        "ya pagué pero", "me cobraron mal", "fraude", "no autoricé",
        "disput", "chargeback",
    ]):
        reasons.append("PAYMENT_DISPUTE")

    # E7: refund a cuenta distinta
    if any(w in rtext for w in [
        "otra cuenta", "diferente tarjeta", "mi nueva cuenta",
        "transferir a",
    ]):
        reasons.append("REFUND_TO_OTHER_ACCOUNT")

    # E8: descuento futuro
    if any(w in rtext for w in [
        "descuento", "rebaja", "promoción si", "cupón a cambio",
    ]):
        reasons.append("DISCOUNT_REQUEST")

    # E10: hostile (heurística simple)
    if any(w in rtext for w in [
        "estafa", "ladrón", "demand", "mier", "estúp", "incompetent",
    ]):
        reasons.append("CUSTOMER_HOSTILE")

    # E13: tenant deshabilita auto-void CARD
    if policy.escalate_card_voids:
        payment_method = (payment or {}).get("payment_method_type", "").upper()
        if payment_method == "CARD":
            reasons.append("POLICY_DISABLED")

    return reasons


# ── Pipeline principal ───────────────────────────────────────────────────────

# Actores staff/sistema: un humano (o el sistema) ya está decidiendo — la triage
# se REGISTRA en la auditoría pero no bloquea. Solo el canal autónomo (cliente
# final vía bot) se bloquea y escala.
# OJO: `actor` debe ser un valor del enum DB `order_cancellation_actor`
# ('customer' | 'operator' | 'system_auto' | 'system_fraud' — migración
# 20260606000000; 'operator' cubre "agente/manager desde Tenant Console", la
# granularidad owner/manager va en `cancelled_by_user_id` + audit_log). El
# live M2.2 destapó que cualquier otro valor rompe el insert/update (22P02).
_STAFF_ACTORS = {"operator", "system_auto", "system_fraud"}


async def cancel_order(
    supabase: Any,
    request: CancellationRequest,
    *,
    ports: CancellationPorts = CancellationPorts(),
) -> CancellationResult:
    """Pipeline production-grade de cancelación (Ley 1480).

    Pasos:
      1. Lookup orden + cargas asociadas (payment, shipment).
      2. Load tenant policy.
      3. Triage escalation reasons → si hay Y el actor es customer (bot):
         return requires_escalation=True. Si el actor es staff: se registran
         en la auditoría y se procede (el humano ya está decidiendo).
      4. Insert order_cancellations row (status='pending').
      5. Stock release/reverse (reservas + movements, RPCs idempotentes).
      6. Wompi void (si aplica, vía puerto) o marcar refund_pending_manual.
      7. Cancel guía carrier (si aplica, vía puerto).
      8. orders.status='cancelled' + cancellation_id link.
      9. Mensajes (cliente + operador) en el resultado — el ADAPTADOR los envía.
      10. Update cancellation row status='completed'/'partial_failure'.
    """
    # 1. Lookup orden
    try:
        order = (
            supabase.table("orders")
            .select("id, tenant_id, status, total_amount, conversation_id, "
                    "contact_id, payment_method")
            .eq("id", request.order_id)
            .eq("tenant_id", request.tenant_id)
            .single()
            .execute()
        ).data
    except Exception as exc:
        return CancellationResult(
            success=False, status="failed",
            error=f"orden no encontrada: {exc}",
            customer_message=(
                "No encuentro ese pedido en mi sistema. ¿Me confirmas el "
                "número (8 caracteres después del #)?"
            ),
        )
    if not order:
        return CancellationResult(
            success=False, status="failed",
            error="orden no existe",
            customer_message="No encuentro ese pedido. ¿Me confirmas el número?",
        )

    # Idempotency: orden ya cancelada
    if (order.get("status") or "").lower() == "cancelled":
        return CancellationResult(
            success=True, status="completed",
            customer_message=(
                f"Tu pedido #{request.order_id[:8].upper()} ya estaba "
                f"cancelado anteriormente. ¿Te ayudo con algo más?"
            ),
        )

    # 2. Load policy
    policy = load_policy(supabase, request.tenant_id)

    # Cargar payment + shipment para triage.
    # Schema real `payments` NO tiene columnas dedicadas payment_method_type/paid_at;
    # extraemos del raw_webhook (Wompi event payload) cuando aplique.
    payment_row = None
    try:
        payments = (
            supabase.table("payments")
            .select("status, wompi_status, wompi_txn_id, amount_in_cents, raw_webhook")
            .eq("order_id", request.order_id)
            .eq("tenant_id", request.tenant_id)  # A6.2.7: defensa cross-tenant
            .order("created_at", desc=True).limit(1).execute()
        ).data or []
        payment_row = payments[0] if payments else None
        if payment_row:
            _hydrate_payment_from_webhook(payment_row)
    except Exception:
        pass

    shipment_row = None
    try:
        shipments = (
            supabase.table("shipments")
            .select("status, tracking_number, carrier, service")
            .eq("order_id", request.order_id)
            .eq("tenant_id", request.tenant_id)  # A6.2.7: defensa cross-tenant
            .order("created_at", desc=True).limit(1).execute()
        ).data or []
        shipment_row = shipments[0] if shipments else None
    except Exception:
        pass

    # 3. Triage escalation — bloquea SOLO al canal customer (bot autónomo).
    escalation_reasons = detect_escalation_reasons(
        order=order, request=request, policy=policy,
        shipment=shipment_row, payment=payment_row,
    )
    staff_override = bool(escalation_reasons) and request.actor in _STAFF_ACTORS
    if escalation_reasons and not staff_override:
        # Persistir audit con status='pending' + escalated=true
        cancel_id = insert_cancellation_row(
            supabase, order, request, payment_row, shipment_row,
            policy, status="pending", escalated=True,
            escalation_reason=", ".join(escalation_reasons),
        )
        return _build_escalation_result(
            cancellation_id=cancel_id,
            reasons=escalation_reasons,
            order=order,
            request=request,
            policy=policy,
        )

    # 4. Insert cancellation row (status='pending'). Staff con razones de riesgo:
    # procede pero las registra en la fila (auditoría SIC conserva la señal).
    cancel_id = insert_cancellation_row(
        supabase, order, request, payment_row, shipment_row,
        policy, status="pending", escalated=False,
        escalation_reason=", ".join(escalation_reasons) if staff_override else "",
    )

    result = CancellationResult(
        success=True, cancellation_id=cancel_id, status="pending",
    )

    # 5. Stock release/reverse
    stock_restored, stock_method = _restore_stock(
        supabase, order_id=request.order_id, tenant_id=request.tenant_id,
        items=request.items, ports=ports,
    )

    # 6. Wompi refund/void
    refund_method, refund_status, refund_amount = _process_refund(
        supabase, order=order, payment=payment_row, policy=policy, ports=ports,
    )
    result.refund_amount_cents = refund_amount
    result.refund_method = refund_method
    result.refund_status = refund_status

    # 7. Cancel guía carrier
    shipping_cancelled, shipping_method = await _cancel_shipping(
        supabase, tenant_id=request.tenant_id, shipment=shipment_row, ports=ports,
    )

    # 8. orders.status='cancelled'
    try:
        supabase.table("orders").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancelled_by_actor": request.actor,
            "cancellation_id": cancel_id,
        }).eq("id", request.order_id).eq("tenant_id", request.tenant_id).execute()
    except Exception as exc:
        logger.error("[CANCEL] update orders.status failed: %s", exc)

    # 9. Customer message
    short_id = request.order_id[:8].upper()
    result.customer_message = _compose_customer_message(
        short_id=short_id, refund_method=refund_method,
        refund_amount_cents=refund_amount, policy=policy,
    )

    # Operator notification (si refund manual)
    if refund_status == "pending_manual":
        result.operator_notification = (
            f"⚠️ Refund manual requerido — Pedido #{short_id}\n"
            f"Monto: ${refund_amount / 100:,.0f} COP\n"
            f"Método: {payment_row.get('payment_method_type', '?') if payment_row else '?'}\n"
            f"Wompi txn: {payment_row.get('wompi_txn_id', '?') if payment_row else '?'}\n"
            f"Plazo legal Ley 1480: {policy.manual_refund_legal_days} días calendario.\n"
            f"Acción: ir a dashboard.wompi.co + ejecutar refund manual."
        )

    # 10. Update cancellation status
    completed_at = datetime.now(timezone.utc).isoformat()
    final_status = (
        "completed" if (
            stock_restored
            and (refund_status in {"completed", "not_applicable"})
            and (shipping_cancelled or shipment_row is None)
        ) else "partial_failure"
    )
    try:
        supabase.table("order_cancellations").update({
            "status": final_status,
            "amount_refunded_cents": refund_amount,
            "refund_method": refund_method,
            "refund_status": refund_status,
            "refund_completed_at": (
                completed_at if refund_status == "completed" else None
            ),
            "shipping_cancelled": shipping_cancelled,
            "shipping_cancel_method": shipping_method,
            "shipping_cancel_tracking": (
                shipment_row.get("tracking_number") if shipment_row else None
            ),
            "stock_restored": stock_restored,
            "stock_restore_method": stock_method,
            "completed_at": completed_at,
        }).eq("id", cancel_id).eq("tenant_id", request.tenant_id).execute()
    except Exception as exc:
        logger.warning("[CANCEL] update cancellation row failed: %s", exc)

    result.status = final_status
    return result


# ── Helpers internos ─────────────────────────────────────────────────────────

def _hydrate_payment_from_webhook(payment: dict) -> None:
    """Extrae payment_method_type + paid_at desde raw_webhook (Wompi event).

    El schema `payments` actual NO tiene columnas dedicadas. La info real está
    en raw_webhook.data.transaction.{payment_method_type, finalized_at}.
    Mutamos el dict in-place para que el resto del pipeline lo lea uniforme.
    """
    rw = payment.get("raw_webhook") or {}
    try:
        txn = ((rw.get("data") or {}).get("transaction") or {})
    except Exception:
        txn = {}
    if not payment.get("payment_method_type"):
        payment["payment_method_type"] = txn.get("payment_method_type") or ""
    if not payment.get("paid_at"):
        payment["paid_at"] = txn.get("finalized_at") or txn.get("created_at")


def insert_cancellation_row(
    supabase: Any, order: dict, request: CancellationRequest,
    payment: Optional[dict], shipment: Optional[dict],
    policy: TenantPolicy, *, status: str, escalated: bool,
    escalation_reason: str = "",
) -> str:
    cancel_id = str(uuid.uuid4())
    items_json = None
    if request.items:
        items_json = [
            {
                "cart_item_id": it.cart_item_id,
                "product_id": it.product_id,
                "variation_id": it.variation_id,
                "qty": it.qty,
                "unit_price_cents": it.unit_price_cents,
            }
            for it in request.items
        ]
    try:
        supabase.table("order_cancellations").insert({
            "id": cancel_id,
            "tenant_id": request.tenant_id,
            "order_id": request.order_id,
            "conversation_id": request.conversation_id,
            "cancelled_by_actor": request.actor,
            "cancelled_by_user_id": request.user_id,
            "status": status,
            "reason_code": request.reason_code,
            "reason_text": request.reason_text,
            "items_cancelled_json": items_json,
            "escalated_to_operator": escalated,
            "escalation_reason": escalation_reason or None,
            "ip_address": request.ip_address,
            "legal_basis": "ley_1480_estatuto_consumidor",
        }).execute()
    except Exception as exc:
        logger.error("[CANCEL] insert audit row failed: %s", exc)
    return cancel_id


def _build_escalation_result(
    *, cancellation_id: str, reasons: list[str],
    order: dict, request: CancellationRequest, policy: TenantPolicy,
) -> CancellationResult:
    short_id = request.order_id[:8].upper()
    customer_msg = _escalation_customer_message(reasons, short_id, order, policy)
    operator_msg = (
        f"🚨 Cancelación escalada — Pedido #{short_id}\n"
        f"Razones: {', '.join(reasons)}\n"
        f"Cliente dijo: \"{request.reason_text[:200]}\"\n"
        f"Acción: revisar y decidir manualmente."
    )
    return CancellationResult(
        success=False, cancellation_id=cancellation_id, status="pending",
        requires_escalation=True, escalation_reasons=reasons,
        customer_message=customer_msg, operator_notification=operator_msg,
    )


def _escalation_customer_message(
    reasons: list[str], short_id: str, order: dict, policy: TenantPolicy,
) -> str:
    """Mensaje natural al cliente según razón principal de escalación.

    Recibe la política porque el plazo de retracto es del TENANT (la ley da 5
    días hábiles como piso y un comerciante puede ofrecer más).
    """
    primary = reasons[0]
    if primary == "ORDER_IN_TRANSIT":
        return (
            f"Tu pedido *#{short_id}* ya está en ruta. No puedo cancelarlo "
            f"desde aquí, pero:\n"
            f"🔄 Puedes rechazarlo cuando el courier te lo entregue — "
            f"se devuelve y procesamos tu reembolso completo.\n"
            f"👤 También puedo conectarte con un especialista. ¿Cuál prefieres?"
        )
    if primary == "ORDER_DELIVERED":
        return (
            f"Tu pedido *#{short_id}* ya fue entregado. Si quieres devolverlo, "
            f"tienes *derecho de retracto* por "
            f"*{policy.retracto_window_business_days} días hábiles* desde que lo "
            f"recibiste (Ley 1480).\n\nTe conecto con un especialista para "
            f"procesar tu retracto."
        )
    if primary == "PRODUCT_DEFECT_CLAIMED":
        return (
            f"Lo siento por la experiencia. Si tu producto vino defectuoso, "
            f"aplica *garantía legal* (Ley 1480 Art. 11), no cancelación.\n\n"
            f"Te conecto con un especialista del equipo para procesar tu "
            f"reclamo y solución (cambio, refund completo, etc.)."
        )
    if primary == "MISSING_PACKAGE":
        return (
            f"Entiendo, eso es preocupante. Si tu pedido *#{short_id}* no "
            f"llegó cuando debía, vamos a investigar con el courier.\n\n"
            f"Te conecto con un especialista que revisa el tracking + "
            f"coordina con la transportadora."
        )
    if primary == "PAYMENT_DISPUTE":
        return (
            f"Sobre temas de pago necesitamos verificación detallada. "
            f"Te conecto inmediatamente con un especialista para que revise "
            f"tu caso."
        )
    if primary == "HIGH_VALUE":
        return (
            f"Por el monto de tu pedido *#{short_id}*, necesito que un "
            f"especialista del equipo lo procese para asegurarnos de hacerlo "
            f"correctamente.\n\nTe conectan en breve."
        )
    if primary == "REFUND_TO_OTHER_ACCOUNT":
        return (
            f"Para procesar reembolsos a cuentas distintas necesitamos "
            f"verificación adicional. Te conecto con un especialista."
        )
    if primary == "DISCOUNT_REQUEST":
        return (
            f"Vamos a revisar tu caso completo (cancelación + descuento). "
            f"Te conecto con un especialista que puede aprobar promociones."
        )
    if primary == "CUSTOMER_HOSTILE":
        return (
            f"Entiendo tu frustración y quiero ayudarte bien. Te conecto "
            f"directo con un especialista del equipo."
        )
    # Default
    return (
        f"Voy a conectarte con un especialista del equipo para procesar "
        f"correctamente tu solicitud sobre el pedido *#{short_id}*."
    )


def _restore_stock(
    supabase: Any, *, order_id: str, tenant_id: str,
    items: Optional[list[CancellationItem]],
    ports: CancellationPorts = CancellationPorts(),
) -> tuple[bool, str]:
    """Revierte stock vía stock_movements + libera reservas activas.

    Cancelación total → reverse todas las movements consumed.
    Cancelación parcial → reverse solo las variations en items list.

    La liberación de reservas llama DIRECTO la RPC `rpc_stock_reservation_release`
    (misma traza que la cadena release_by_cart→release_by_id del bot — el wrapper
    del orchestrator es un thin wrapper sobre esa RPC; el paquete no lo importa
    porque vive en el rootDir del bot).
    """
    # Liberar reservas activas si hay (caso pre-confirmed cancel).
    try:
        carts = (
            supabase.table("conversation_carts")
            .select("id").eq("converted_order_id", order_id).eq("tenant_id", tenant_id)
            .execute()
        ).data or []
        for c in carts:
            try:
                res_list = (
                    supabase.table("stock_reservations")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .eq("cart_id", c["id"])
                    .eq("status", "active")
                    .execute()
                ).data or []
                for res_row in res_list:
                    try:
                        # A11 IDOR: p_tenant_id = tenant autenticado → filtra cross-tenant.
                        supabase.rpc("rpc_stock_reservation_release", {
                            "p_reservation_id": res_row["id"],
                            "p_tenant_id": tenant_id,
                        }).execute()
                    except Exception as exc:
                        logger.warning(
                            "[CANCEL] release reservation=%s failed: %s", res_row["id"], exc,
                        )
            except Exception as exc:
                logger.warning("[CANCEL] lookup reservas cart=%s falló: %s", c["id"], exc)
    except Exception:
        pass

    # Reverse stock_movements consumed (caso post-confirmed cancel).
    # Inserta movement '+qty' reverso para cada movement original con
    # reason IN ('reservation_consumed', 'sale') del order.
    try:
        # BLOQUE C item 4: reponer los decrementos por venta — tanto
        # 'reservation_consumed' (flujo conversacional) como 'sale' (orden
        # manual/COD directa).
        movements = (
            supabase.table("stock_movements")
            .select("variation_id, delta, tenant_id")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .in_("reason", ["reservation_consumed", "sale"])
            .execute()
        ).data or []

        # Filtrar por items si es cancelación parcial
        target_variations = None
        if items:
            target_variations = {it.variation_id for it in items}

        # Agregar por variación: si una variante tiene varios movimientos de
        # decremento, sumar para reponer el total en UNA llamada (el guard
        # idempotente 'cancellation_refund' por (order,var) colapsaría múltiples).
        restore_by_var: dict = {}
        for mv in movements:
            var_id = mv.get("variation_id")
            if not var_id or (target_variations and var_id not in target_variations):
                continue
            qty = abs(int(mv.get("delta") or 0))
            if qty > 0:
                restore_by_var[var_id] = restore_by_var.get(var_id, 0) + qty

        reversed_count = 0
        for var_id, qty_to_restore in restore_by_var.items():
            # BLOQUE C item 4: reposición ATÓMICA e IDEMPOTENTE vía RPC. El
            # movement 'cancellation_refund' (ON CONFLICT DO NOTHING) es el guard:
            # un retry de la cancelación NO re-repone.
            try:
                _rpc = supabase.rpc("rpc_stock_restore", {
                    "p_tenant_id": tenant_id,
                    "p_variation_id": var_id,
                    "p_qty": qty_to_restore,
                    "p_order_id": order_id,
                    "p_reason": "cancellation_refund",
                }).execute()
                reversed_count += 1
            except Exception as exc:
                logger.warning(
                    "[CANCEL] reverse movement var=%s failed: %s", var_id, exc,
                )
                continue
            # Hook post-reposición (puerto): la consola sincroniza MeLi; el bot
            # lo gana al adoptar el paquete en B-2. Nunca bloquea el restock.
            if ports.on_stock_restored is not None and isinstance(_rpc.data, int):
                try:
                    ports.on_stock_restored(var_id, _rpc.data)
                except Exception as exc:
                    logger.warning(
                        "[CANCEL] on_stock_restored var=%s falló (no bloquea): %s",
                        var_id, exc,
                    )

        if reversed_count > 0:
            return True, "stock_movements_reversed"
        return True, "reservation_released"
    except Exception as exc:
        logger.warning("[CANCEL] restore_stock crashed: %s", exc)
        return False, "failed"


def _process_refund(
    supabase: Any, *, order: dict, payment: Optional[dict],
    policy: TenantPolicy, ports: CancellationPorts,
) -> tuple[Optional[str], str, int]:
    """Determina si auto-void es posible y lo ejecuta vía puerto. Si no, manual.

    Returns: (refund_method, refund_status, amount_cents)
    """
    if not payment:
        # Sin payment → era pre-pago (cart pending_payment) o COD nunca cobrado.
        return "no_refund_no_payment", "not_applicable", 0

    payment_status = (payment.get("status") or "").lower()
    payment_method = (payment.get("payment_method_type") or "").upper()
    amount = int(payment.get("amount_in_cents") or 0)

    # COD: never had physical money
    if payment_method == "" or payment_status in {"pending", "cod_pending", "declined"}:
        return "no_refund_no_payment", "not_applicable", 0

    if (order.get("payment_method") or "").lower() == "cod":
        # COD confirmed pero no se recogió → no aplica refund
        return "cod_not_collected", "not_applicable", 0

    if policy.escalate_card_voids:
        # Tenant prefiere SIEMPRE manual
        return "wompi_dashboard_manual", "pending_manual", amount

    # Auto-void si CARD + ventana + el canal tiene puertos de void
    if payment_method == "CARD" and payment.get("paid_at"):
        if ports.void_credentials is None or ports.void_payment is None:
            # El canal no soporta auto-void (equivalente al import-failure del
            # bot) → refund manual.
            logger.error("[CANCEL] puertos de void no inyectados — manual")
            return "wompi_dashboard_manual", "pending_manual", amount

        if not is_void_eligible(payment_method, payment.get("paid_at")):
            logger.info(
                "[CANCEL] void NOT eligible (window or method) txn=%s",
                payment.get("wompi_txn_id"),
            )
            return "wompi_dashboard_manual", "pending_manual", amount

        creds = ports.void_credentials(order["tenant_id"])
        if not creds or not creds[0]:
            logger.warning(
                "[CANCEL] tenant=%s sin wompi private_key — manual",
                order["tenant_id"],
            )
            return "wompi_dashboard_manual", "pending_manual", amount
        private_key, environment = creds

        txn_id = payment.get("wompi_txn_id")
        if not txn_id:
            logger.warning("[CANCEL] payment sin wompi_txn_id — manual")
            return "wompi_dashboard_manual", "pending_manual", amount

        try:
            ports.void_payment(private_key, environment or "sandbox", txn_id)
            # Wompi POST /void devuelve la transacción PRE-void (status=APPROVED)
            # y procesa el void asíncrono. El paso a VOIDED llega vía webhook
            # `transaction.updated` ~segundos después. HTTP 200 sin excepción
            # significa que Wompi aceptó el void — marcamos completed y
            # actualizamos wompi_status localmente para coherencia (el webhook
            # subsecuente será idempotente).
            try:
                # A6.2.7: wompi_txn_id NO es UNIQUE a nivel DB (índice parcial
                # no-unique). Filtrar por tenant evita VOID de payment ajeno.
                supabase.table("payments").update({
                    "wompi_status": "VOIDED",
                }).eq("wompi_txn_id", txn_id).eq("tenant_id", order["tenant_id"]).execute()
            except Exception as exc:
                logger.warning(
                    "[CANCEL] update payments.wompi_status=VOIDED failed: %s",
                    exc,
                )
            return "wompi_void_auto", "completed", amount
        except Exception as exc:
            logger.warning(
                "[CANCEL] wompi void failed txn=%s: %s — escalating manual",
                txn_id, exc,
            )

    # Default: manual refund operador
    return "wompi_dashboard_manual", "pending_manual", amount


async def _cancel_shipping(
    supabase: Any, *, tenant_id: str, shipment: Optional[dict],
    ports: CancellationPorts,
) -> tuple[bool, Optional[str]]:
    """Cancela guía del carrier si soporta API + no en tránsito."""
    if not shipment:
        return False, "not_applicable"

    status = (shipment.get("status") or "").lower()
    if status in {"picked_up", "in_transit", "out_for_delivery", "delivered"}:
        return False, "manual_operator_call"

    tracking = shipment.get("tracking_number")
    if not tracking:
        return False, "not_applicable"

    # Modo simulación (sandbox sin guía real): no hay API call que hacer, solo
    # marcamos shipments.status='cancelled' para coherencia.
    if status == "simulated":
        try:
            supabase.table("shipments").update({
                "status": "cancelled",
            }).eq("tracking_number", tracking).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            logger.warning("[CANCEL] update shipment cancelled (sim) failed: %s", exc)
        return True, "simulated_no_api_call"

    if ports.cancel_shipping_guide is None:
        return False, "manual_operator_call"

    try:
        result = await ports.cancel_shipping_guide(tenant_id, tracking)
        if result.get("ok"):
            try:
                supabase.table("shipments").update({
                    "status": "cancelled",
                }).eq("tracking_number", tracking).eq("tenant_id", tenant_id).execute()
            except Exception:
                pass
            # El label del método lo reporta el puerto (auditoría fiel al
            # proveedor real: "aveonline_api" hoy) — default neutro si no viene.
            return True, result.get("method") or "carrier_api"
        return False, "manual_operator_call"
    except Exception as exc:
        logger.warning("[CANCEL] carrier cancel falló: %s", exc)
        return False, "manual_operator_call"


def _compose_customer_message(
    *, short_id: str, refund_method: Optional[str],
    refund_amount_cents: int, policy: TenantPolicy,
) -> str:
    """Mensaje natural empático según refund method."""
    base = f"Listo, cancelé tu pedido *#{short_id}*."

    if refund_method == "no_refund_no_payment":
        return f"{base} No se cobró nada.\n\n¿Hacemos un pedido nuevo o algo más?"

    if refund_method == "cod_not_collected":
        return (
            f"{base} Como era pago contra entrega, no hay nada que devolver. "
            f"Liberé el stock de tus productos.\n\n¿Hacemos un pedido nuevo "
            f"o algo más?"
        )

    amount_fmt = f"${refund_amount_cents / 100:,.0f}".replace(",", ".")

    if refund_method == "wompi_void_auto":
        return (
            f"{base}\n\n💰 *Reembolso:* {amount_fmt} COP procesado. Wompi "
            f"devolverá el dinero al medio de pago que usaste en "
            f"*3-5 días hábiles*. Te llegará confirmación por email.\n\n"
            f"¿Hacemos un pedido nuevo o algo más?"
        )

    if refund_method == "wompi_dashboard_manual":
        return (
            f"{base}\n\n💰 *Reembolso:* {amount_fmt} COP en proceso. Un "
            f"especialista de nuestro equipo te lo confirmará en breve "
            f"(plazo máximo *{policy.manual_refund_legal_days} días "
            f"calendario* por Ley 1480).\n\nTe llegará confirmación por "
            f"email. ¿Algo más?"
        )

    return base
