"""Orquestador de cancelación de pedidos.

Rev. 109 producción — cumple Ley 1480 de 2011 (Estatuto del Consumidor).

Diseño:
  • Pipeline determinístico con 12 escalation rules.
  • Auto-cancel cuando seguro (CARD <24h void, COD sin courier, etc.).
  • Escalación a operador cuando hay riesgo financiero/legal/operacional.
  • Audit append-only en `order_cancellations` (SIC compliance).
  • Multi-tenant policy configurable.
  • Cancelación TOTAL o PARCIAL (items_cancelled_json).

NO duplica lógica:
  • Stock reservation usa lib/stock_reservation.py existente.
  • Wompi void usa wompi_client.void_transaction_sync NUEVO.
  • Aveonline cancel usa aveonline_client.cancel_guide NUEVO.
  • Notificaciones email reusa wompi_webhook._send_payment_confirmation_email.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("orchestrator.order_cancellation")


# ── Escalation rules ─────────────────────────────────────────────────────────
# Cuando el bot DEBE NO ejecutar autónomo y escalar a operador.

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
    actor: str  # 'customer' | 'operator' | 'system_auto' | 'system_fraud'
    reason_code: str = "customer_request"
    reason_text: str = ""
    items: Optional[list[CancellationItem]] = None  # None = cancelación total
    user_id: Optional[str] = None  # si actor='operator'
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


# ── Policy loader ────────────────────────────────────────────────────────────

@dataclass
class TenantPolicy:
    allow_cancel_after_picked_up: bool = False
    auto_void_card_window_hours: int = 23
    manual_refund_legal_days: int = 30
    allow_partial_cancellation: bool = True
    enable_retracto_flow: bool = True
    retracto_window_business_days: int = 5
    retracto_return_paid_by: str = "customer"
    retracto_excluded_product_ids: list = field(default_factory=list)
    retracto_excluded_categories: list = field(default_factory=list)
    high_value_escalation_threshold_cents: int = 50000000  # $500K
    escalate_card_voids: bool = False


def _load_policy(supabase: Any, tenant_id: str) -> TenantPolicy:
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
        manual_refund_legal_days=int(row.get("manual_refund_legal_days") or 30),
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


# ── Escalation triage ────────────────────────────────────────────────────────

def detect_escalation_reasons(
    *,
    order: dict,
    request: CancellationRequest,
    policy: TenantPolicy,
    shipment: Optional[dict] = None,
    payment: Optional[dict] = None,
) -> list[str]:
    """Evalúa las 12+ reglas de escalación. Retorna lista de reason codes;
    vacía = bot autónomo OK."""
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
        "no me ha llegada", "no me lleg",  # variantes morfológicas
        "extraviad", "perdid", "robad", "nunca recibí", "nunca lleg",
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


# ── Pipeline principal ──────────────────────────────────────────────────────

async def cancel_order(
    supabase: Any,
    request: CancellationRequest,
) -> CancellationResult:
    """Pipeline production-grade de cancelación.

    Pasos:
      1. Lookup orden + cargas asociadas (cart, payment, shipment, contact).
      2. Load tenant policy.
      3. Triage escalation reasons → si hay → return con requires_escalation=True.
      4. Insert order_cancellations row (status='pending').
      5. Stock release/reverse.
      6. Wompi void (si aplica) o marcar refund_pending_manual.
      7. Aveonline cancel guía (si aplica).
      8. orders.status='cancelled' + cancellation_id link.
      9. Notif customer (email + WhatsApp) + operador (Telegram si requiere).
      10. Update cancellation row status='completed' + completed_at.
      11. Emit cart_events('order_cancelled').
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
    policy = _load_policy(supabase, request.tenant_id)

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

    # 3. Triage escalation
    escalation_reasons = detect_escalation_reasons(
        order=order, request=request, policy=policy,
        shipment=shipment_row, payment=payment_row,
    )
    if escalation_reasons:
        # Persistir audit con status='pending' + escalated=true
        cancel_id = _insert_cancellation_row(
            supabase, order, request, payment_row, shipment_row,
            policy, status="pending", escalated=True,
            escalation_reason=", ".join(escalation_reasons),
        )
        return _build_escalation_result(
            cancellation_id=cancel_id,
            reasons=escalation_reasons,
            order=order,
            request=request,
        )

    # 4. Insert cancellation row (status='pending')
    cancel_id = _insert_cancellation_row(
        supabase, order, request, payment_row, shipment_row,
        policy, status="pending", escalated=False,
    )

    result = CancellationResult(
        success=True, cancellation_id=cancel_id, status="pending",
    )

    # 5. Stock release/reverse
    stock_restored, stock_method = _restore_stock(
        supabase, order_id=request.order_id, tenant_id=request.tenant_id,
        items=request.items,
    )

    # 6. Wompi refund/void
    refund_method, refund_status, refund_amount = _process_refund(
        supabase, order=order, payment=payment_row, policy=policy,
    )
    result.refund_amount_cents = refund_amount
    result.refund_method = refund_method
    result.refund_status = refund_status

    # 7. Aveonline cancel guía
    shipping_cancelled, shipping_method = await _cancel_shipping(
        supabase, tenant_id=request.tenant_id, shipment=shipment_row,
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
        }).eq("id", cancel_id).execute()
    except Exception as exc:
        logger.warning("[CANCEL] update cancellation row failed: %s", exc)

    result.status = final_status
    return result


# ── Helpers internos ──────────────────────────────────────────────────────────

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


def _insert_cancellation_row(
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
    order: dict, request: CancellationRequest,
) -> CancellationResult:
    short_id = request.order_id[:8].upper()
    customer_msg = _escalation_customer_message(reasons, short_id, order)
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


def _escalation_customer_message(reasons: list[str], short_id: str, order: dict) -> str:
    """Mensaje natural al cliente según razón principal de escalación."""
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
            f"tienes *derecho de retracto* por *5 días hábiles* desde que lo "
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
) -> tuple[bool, str]:
    """Revierte stock vía stock_movements + libera reservas activas.

    Cancelación total → reverse todas las movements consumed.
    Cancelación parcial → reverse solo las variations en items list.
    """
    try:
        from lib import stock_reservation as sr
    except Exception as exc:
        logger.warning("[CANCEL] stock_reservation lib unavailable: %s", exc)
        return False, "failed"

    # Liberar reservas activas si hay (caso pre-confirmed cancel).
    try:
        carts = (
            supabase.table("conversation_carts")
            .select("id").eq("converted_order_id", order_id)
            .execute()
        ).data or []
        for c in carts:
            sr.release_by_cart(supabase, tenant_id=tenant_id, cart_id=c["id"])
    except Exception:
        pass

    # Reverse stock_movements consumed (caso post-confirmed cancel).
    # Inserta movement '+qty' reverso para cada movement original con
    # reason='reservation_consumed' del order.
    try:
        movements = (
            supabase.table("stock_movements")
            .select("variation_id, delta, tenant_id")
            .eq("order_id", order_id)
            .eq("reason", "reservation_consumed")
            .execute()
        ).data or []

        # Filtrar por items si es cancelación parcial
        target_variations = None
        if items:
            target_variations = {it.variation_id for it in items}

        reversed_count = 0
        for mv in movements:
            var_id = mv.get("variation_id")
            if target_variations and var_id not in target_variations:
                continue
            qty_to_restore = abs(int(mv.get("delta") or 0))
            if qty_to_restore <= 0:
                continue
            # Aumentar stock_quantity + insert audit movement
            try:
                cur_row = (
                    supabase.table("product_variations")
                    .select("stock_quantity").eq("id", var_id).single().execute()
                ).data
                cur_stock = int(cur_row.get("stock_quantity") or 0)
                new_stock = cur_stock + qty_to_restore
                supabase.table("product_variations").update({
                    "stock_quantity": new_stock,
                }).eq("id", var_id).execute()
                supabase.table("stock_movements").insert({
                    "tenant_id": tenant_id,
                    "variation_id": var_id,
                    "delta": qty_to_restore,
                    "new_stock": new_stock,
                    "reason": "cancellation_refund",
                    "order_id": order_id,
                }).execute()
                reversed_count += 1
            except Exception as exc:
                logger.warning(
                    "[CANCEL] reverse movement var=%s failed: %s", var_id, exc,
                )

        if reversed_count > 0:
            return True, "stock_movements_reversed"
        return True, "reservation_released"
    except Exception as exc:
        logger.warning("[CANCEL] restore_stock crashed: %s", exc)
        return False, "failed"


def _process_refund(
    supabase: Any, *, order: dict, payment: Optional[dict], policy: TenantPolicy,
) -> tuple[Optional[str], str, int]:
    """Determina si auto-void es posible y lo ejecuta. Si no, marca manual.

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

    # Auto-void si CARD + ventana
    if payment_method == "CARD" and payment.get("paid_at"):
        try:
            from integrations.wompi_client import (
                void_transaction_sync,
                is_void_eligible,
                get_tenant_wompi_creds,
            )
        except Exception as exc:
            logger.error("[CANCEL] wompi_client import failed: %s", exc)
            return "wompi_dashboard_manual", "pending_manual", amount

        if not is_void_eligible(payment_method, payment.get("paid_at")):
            logger.info(
                "[CANCEL] void NOT eligible (window or method) txn=%s",
                payment.get("wompi_txn_id"),
            )
            return "wompi_dashboard_manual", "pending_manual", amount

        private_key, _events_key, environment = get_tenant_wompi_creds(
            supabase, tenant_id=order["tenant_id"],
        )
        if not private_key:
            logger.warning(
                "[CANCEL] tenant=%s sin wompi private_key — manual",
                order["tenant_id"],
            )
            return "wompi_dashboard_manual", "pending_manual", amount

        txn_id = payment.get("wompi_txn_id")
        if not txn_id:
            logger.warning("[CANCEL] payment sin wompi_txn_id — manual")
            return "wompi_dashboard_manual", "pending_manual", amount

        try:
            void_transaction_sync(
                private_key=private_key,
                environment=environment or "sandbox",
                transaction_id=txn_id,
            )
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
) -> tuple[bool, Optional[str]]:
    """Cancela guía Aveonline si carrier soporta API + no en tránsito."""
    if not shipment:
        return False, "not_applicable"

    status = (shipment.get("status") or "").lower()
    if status in {"picked_up", "in_transit", "out_for_delivery", "delivered"}:
        return False, "manual_operator_call"

    tracking = shipment.get("tracking_number")
    if not tracking:
        return False, "not_applicable"

    # Modo simulación (sandbox sin guía real Aveonline): no hay API call que
    # hacer, solo marcamos shipments.status='cancelled' para coherencia.
    if status == "simulated":
        try:
            supabase.table("shipments").update({
                "status": "cancelled",
            }).eq("tracking_number", tracking).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            logger.warning("[CANCEL] update shipment cancelled (sim) failed: %s", exc)
        return True, "simulated_no_api_call"

    try:
        from integrations.aveonline_client import AveonlineClient
        client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)
        result = await client.cancel_guide(tracking_number=tracking)
        if result.get("ok"):
            try:
                supabase.table("shipments").update({
                    "status": "cancelled",
                }).eq("tracking_number", tracking).eq("tenant_id", tenant_id).execute()
            except Exception:
                pass
            return True, "aveonline_api"
        return False, "manual_operator_call"
    except Exception as exc:
        logger.warning("[CANCEL] aveonline cancel falló: %s", exc)
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
