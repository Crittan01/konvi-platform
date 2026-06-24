"""Cart events — log append-only de mutaciones (rev. 104, F1-6).

Capa wrapper sobre `tools/cart_tool.py`. NO reemplaza el cart_tool;
agrega un canal de telemetría/auditoría que se invoca desde los call-sites
de mutación (orchestrator, shipping_quote_tool, payment_link_tool).

Los eventos quedan en la tabla `cart_events` (migration
20260510060000_cart_events.sql). El `conversation_carts` row sigue siendo
estado materializado leído por el bot — los eventos son trazabilidad.

Eventos canónicos (snake_case):
  • item_added — `cart_tool.add_item` exitoso.
  • item_proposed — variant detector con `requires_confirmation=true` (futuro).
  • item_removed — `cart_tool.remove_item` (futuro).
  • qty_changed — cambio de cantidad de un item existente.
  • shipping_quoted — shipping_quote_tool devolvió tarifas.
  • shipping_invalidated — `cart_tool.invalidate_shipping`.
  • carrier_selected — cliente eligió Económica/Rápida.
  • city_changed — cliente pidió cambiar ciudad post-cotización.
  • consent_recorded — cliente aceptó NEEDS_CONSENT.
  • summary_rendered — `_build_order_summary_text` enviado al cliente.
  • payment_link_created — `payment_link_tool` generó link Wompi.
  • order_confirmed — webhook Wompi APPROVED.
  • coupon_applied / coupon_revoked — futuro Fase 4.

Diseño:
  • emisión best-effort (no bloquea cart_tool si falla DB).
  • payload JSONB libre; convención mínima por tipo documentada en docstring.
  • correlation_id (message_id) cuando el evento responde a inbound del cliente.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Tipos canónicos (constantes para evitar typos en call-sites).
EVT_ITEM_ADDED = "item_added"
EVT_ITEM_PROPOSED = "item_proposed"
EVT_ITEM_PROPOSAL_RESOLVED = "item_proposal_resolved"
EVT_ITEM_REMOVED = "item_removed"
EVT_QTY_CHANGED = "qty_changed"
EVT_SHIPPING_QUOTED = "shipping_quoted"
EVT_SHIPPING_INVALIDATED = "shipping_invalidated"
EVT_CARRIER_SELECTED = "carrier_selected"
EVT_CITY_CHANGED = "city_changed"
EVT_CONSENT_RECORDED = "consent_recorded"
EVT_SUMMARY_RENDERED = "summary_rendered"
EVT_PAYMENT_LINK_CREATED = "payment_link_created"
EVT_ORDER_CONFIRMED = "order_confirmed"
# Sem 6 I.2 — Cupones (ADR-0015 D7).
EVT_COUPON_APPLIED = "coupon_applied"
EVT_COUPON_REVOKED = "coupon_revoked"
EVT_COUPON_CONSUMED = "coupon_consumed"


CANONICAL_EVENTS: frozenset[str] = frozenset({
    EVT_ITEM_ADDED, EVT_ITEM_PROPOSED, EVT_ITEM_PROPOSAL_RESOLVED,
    EVT_ITEM_REMOVED, EVT_QTY_CHANGED,
    EVT_SHIPPING_QUOTED, EVT_SHIPPING_INVALIDATED,
    EVT_CARRIER_SELECTED, EVT_CITY_CHANGED,
    EVT_CONSENT_RECORDED, EVT_SUMMARY_RENDERED,
    EVT_PAYMENT_LINK_CREATED, EVT_ORDER_CONFIRMED,
    EVT_COUPON_APPLIED, EVT_COUPON_REVOKED, EVT_COUPON_CONSUMED,
})


def emit(
    supabase: Any,
    *,
    cart_id: str,
    tenant_id: str,
    event_type: str,
    payload: Optional[dict] = None,
    triggered_by: str = "bot",
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """Inserta un evento en `cart_events`. Best-effort.

    Args:
        supabase: cliente service_role (escribe ignorando RLS).
        cart_id, tenant_id: contexto. Si falta cart_id, el evento NO se emite
            (mejor descartar que insertar fila huérfana).
        event_type: uno de `CANONICAL_EVENTS`. Tipos no canónicos generan
            warning pero NO se rechazan (extensibilidad).
        payload: dict con info específica del evento. Convenciones:
            • item_added: {product_id, variation_id, quantity, unit_price_cents}
            • shipping_quoted: {city, carrier, service, total_price_cents}
            • carrier_selected: {carrier, service, shipping_cents}
            • city_changed: {prev_city, new_city}
            • summary_rendered: {total_cents, items_count}
            • payment_link_created: {wompi_link_id, amount_cents, expires_at}
            • order_confirmed: {order_id, txn_id}
            • coupon_applied: {coupon_id, code, type, discount_cents}
            • coupon_revoked: {coupon_id, code, reason}
            • coupon_consumed: {coupon_id, code, discount_cents, order_id}
        triggered_by: 'bot' | 'webhook' | 'human_takeover' | 'cron' | 'system'.
        correlation_id: message_id (uuid string) que originó el evento.

    Returns:
        id del evento insertado, o None si falló.
    """
    if not cart_id or not tenant_id or not event_type:
        return None
    if event_type not in CANONICAL_EVENTS:
        logger.warning(
            "[CART_EVENT] tipo no canónico '%s' (cart=%s) — se inserta igual",
            event_type, cart_id[:8],
        )
    try:
        res = supabase.table("cart_events").insert({
            "cart_id": cart_id,
            "tenant_id": tenant_id,
            "event_type": event_type,
            "event_payload": payload or {},
            "triggered_by": triggered_by,
            "correlation_id": correlation_id,
        }).execute()
        row_id = (res.data or [{}])[0].get("id") if res.data else None
        return row_id
    except Exception as exc:
        # Best-effort: nunca bloqueamos cart_tool por un fallo en la
        # tabla de auditoría. Solo log.
        logger.warning(
            "[CART_EVENT] emit falló cart=%s type=%s: %s",
            cart_id[:8] if cart_id else "?", event_type, exc,
        )
        return None


# ─── Item proposals (Plan A.3 — qty preservation pre-variant) ────────────────
#
# Cuando el cliente declara intención de compra con cantidad explícita pero
# variante ambigua (ej. "quiero 2 jabones de coco" en un catálogo donde
# Coco tiene 60g/100g/150g), no podemos llamar `cart_tool.add_item` aún —
# falta resolver la variante. Si esperamos pasivamente al próximo turno
# (donde el cliente dirá "60 gramos"), perdemos la cantidad declarada.
#
# Patrón propuesta-resolución:
#   1. Detector emite `item_proposed` con qty al detectar mención sin variante.
#   2. Cuando el cliente elige la variante, el detector busca propuestas
#      no resueltas para ese producto y usa su qty.
#   3. Tras `cart_tool.add_item` exitoso, se emite `item_proposal_resolved`
#      con el `proposed_event_id` para marcarla cerrada.
#
# Beneficios:
#   • Sin re-parseo regex de inbounds previos (evita fragilidad heurística).
#   • Auditoría completa: el ledger muestra propuesta → resolución → add.
#   • Idempotente: re-procesar el mismo turno no duplica propuestas (caller
#     puede deduplicar por `(product_id, age < 15min)`).


def emit_item_proposal(
    supabase: Any,
    *,
    cart_id: str,
    tenant_id: str,
    product_id: str,
    title: str,
    quantity: int,
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """Emite `item_proposed` con la cantidad declarada y producto sin
    variante resuelta. Devuelve el `id` del evento (para correlacionar
    luego con `item_proposal_resolved`)."""
    return emit(
        supabase,
        cart_id=cart_id,
        tenant_id=tenant_id,
        event_type=EVT_ITEM_PROPOSED,
        payload={
            "product_id": product_id,
            "title": title,
            "quantity": int(quantity),
            "status": "awaiting_variant",
        },
        correlation_id=correlation_id,
    )


def find_unresolved_proposal(
    supabase: Any,
    *,
    tenant_id: str,
    cart_id: str,
    product_id: str,
    max_lookback: int = 20,
) -> Optional[dict]:
    """Busca la propuesta `item_proposed` más reciente NO resuelta para
    este producto. Devuelve `{event_id, quantity, title}` o None.

    Una propuesta se considera resuelta si existe un evento posterior
    `item_proposal_resolved` con `proposed_event_id` igual a su id.
    """
    if not cart_id or not product_id:
        return None
    try:
        events = (
            supabase.table("cart_events")
            .select("id, event_type, event_payload, created_at")
            .eq("cart_id", cart_id)
            .eq("tenant_id", tenant_id)
            .in_("event_type", [EVT_ITEM_PROPOSED, EVT_ITEM_PROPOSAL_RESOLVED])
            .order("created_at", desc=True)
            .limit(max_lookback)
            .execute()
        ).data or []
    except Exception as exc:
        logger.debug("[CART_EVENT] find_unresolved_proposal falló: %s", exc)
        return None

    resolved_ids: set[str] = {
        str((e.get("event_payload") or {}).get("proposed_event_id") or "")
        for e in events
        if e.get("event_type") == EVT_ITEM_PROPOSAL_RESOLVED
    }
    for e in events:
        if e.get("event_type") != EVT_ITEM_PROPOSED:
            continue
        payload = e.get("event_payload") or {}
        if str(payload.get("product_id")) != str(product_id):
            continue
        if str(e.get("id")) in resolved_ids:
            continue
        try:
            qty = int(payload.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        return {
            "event_id": e.get("id"),
            "quantity": qty,
            "title": payload.get("title") or "",
        }
    return None


def emit_proposal_resolved(
    supabase: Any,
    *,
    cart_id: str,
    tenant_id: str,
    proposed_event_id: str,
    variation_id: str,
    final_quantity: int,
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """Marca una propuesta como resuelta, anclando el `variation_id`
    finalmente elegido y la `final_quantity` que entró al cart."""
    return emit(
        supabase,
        cart_id=cart_id,
        tenant_id=tenant_id,
        event_type=EVT_ITEM_PROPOSAL_RESOLVED,
        payload={
            "proposed_event_id": proposed_event_id,
            "variation_id": variation_id,
            "final_quantity": int(final_quantity),
        },
        correlation_id=correlation_id,
    )
