"""Resolver determinístico del estado agentic.

Toma snapshots de las fuentes de verdad (conversation, cart, contact,
shipping_quotes, orders, payments) y deriva el `AgenticState` actual.

Reglas (en orden — primer match gana):

  1. conversation.status == 'human_handoff'     → HUMAN_HANDOFF
  2. order existe + payment APPROVED/COD_PEND   → POST_PAYMENT
  3. cart.status == 'checkout' + payment_link   → PAYMENT
  4. carrier_options ofrecidas pero sin elegir  → CARRIER_SELECTION
  5. shipping_quote pendiente / en curso        → SHIPPING_QUOTE
  6. cart con items + PII incompleto/consent    → PII_COLLECTION
  7. cart con ≥1 item                            → CART_BUILDING
  8. inbound previos pero 0 items en cart        → EXPLORING
  9. default (primer contacto / silencio)        → GREETING

Notas:
  • El resolver NO escribe el estado en DB — eso lo hace el caller
    (dispatcher) tras invocar `resolve()`. Mantenemos pureza para tests.
  • La función es síncrona — todos los datos vienen del ResolutionContext.
  • Si los datos están incompletos (p.ej. cart=None), se asume el estado
    más conservador (GREETING) para evitar saltos prematuros.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agentic.state_machine.states import AgenticState


@dataclass(slots=True)
class ResolutionContext:
    """Snapshot inmutable de las fuentes de verdad para resolver el estado.

    Todos los campos son opcionales — el resolver maneja ausencia con
    fallback conservador. Los callers (dispatcher) llenan lo que pueden
    leer de DB sin bloquear.
    """

    # Conversation
    conversation_status: str = "bot_active"   # bot_active | human_handoff | closed
    has_prior_inbound: bool = False           # ≥1 inbound message previo
    history_len: int = 0                      # turnos totales en la conv

    # Cart
    cart_status: Optional[str] = None         # open | checkout | abandoned | converted | None
    cart_items_count: int = 0
    cart_payment_method: Optional[str] = None  # cod | credit | None
    cart_has_shipping_quote: bool = False
    cart_has_carrier_selected: bool = False
    cart_has_payment_link: bool = False

    # Contact / PII / consent
    contact_consent_given: bool = False
    contact_has_required_pii: bool = False    # name + (email|doc) + address mínimos

    # Orders / payments
    has_active_order: bool = False
    payment_status: Optional[str] = None      # pending | approved | declined | cod_pending | refunded

    # Misc telemetría
    extra: dict[str, Any] = field(default_factory=dict)


class StateResolver:
    """Derivador determinístico — orden de reglas declarado, primer match gana."""

    def resolve(self, ctx: ResolutionContext) -> AgenticState:
        # 1. Handoff humano siempre gana
        # A11 audit 2026-06-25 (Clase A): el valor canónico del status en DB es
        # "human_takeover" (lo escriben escalation.py, dispatcher, FakeEscalation),
        # NO "human_handoff" → el literal viejo nunca matcheaba (regla dead-code).
        if ctx.conversation_status == "human_takeover":
            return AgenticState.HUMAN_HANDOFF

        # 2. Orden activa + pago resuelto = POST_PAYMENT
        if ctx.has_active_order and ctx.payment_status in {
            "approved", "cod_pending", "cod_collected", "refunded",
        }:
            return AgenticState.POST_PAYMENT

        # 3. Pago en curso (link generado o COD confirmado pendiente)
        if (
            ctx.cart_status == "checkout"
            and ctx.cart_has_payment_link
        ) or ctx.payment_status == "pending":
            return AgenticState.PAYMENT

        # 3.5. Carrier seleccionado + PII + cart listos → PAYMENT (pre-link).
        # Cliente ya eligió transportadora; siguiente acción es generate_payment_link
        # (Wompi para credit / COD direct_response para contraentrega).
        if (
            ctx.cart_items_count > 0
            and ctx.contact_has_required_pii
            and ctx.contact_consent_given
            and ctx.cart_has_shipping_quote
            and ctx.cart_has_carrier_selected
        ):
            return AgenticState.PAYMENT

        # 4. Carrier ofrecido pero no elegido
        if (
            ctx.cart_items_count > 0
            and ctx.cart_has_shipping_quote
            and not ctx.cart_has_carrier_selected
        ):
            return AgenticState.CARRIER_SELECTION

        # 5. Cotización envío en curso (no terminada)
        if (
            ctx.cart_items_count > 0
            and ctx.contact_has_required_pii
            and not ctx.cart_has_shipping_quote
        ):
            return AgenticState.SHIPPING_QUOTE

        # 6. Cart con items pero PII/consent incompletos
        if ctx.cart_items_count > 0 and (
            not ctx.contact_consent_given
            or not ctx.contact_has_required_pii
        ):
            return AgenticState.PII_COLLECTION

        # 7. Cart con items, todo OK pre-checkout
        if ctx.cart_items_count > 0:
            return AgenticState.CART_BUILDING

        # 8. Ya hubo interacción pero 0 items
        if ctx.has_prior_inbound or ctx.history_len > 0:
            return AgenticState.EXPLORING

        # 9. Default
        return AgenticState.GREETING


def build_context_from_records(
    *,
    conversation: dict[str, Any] | None,
    cart: dict[str, Any] | None,
    contact: dict[str, Any] | None,
    order: dict[str, Any] | None = None,
    payment: dict[str, Any] | None = None,
    history_len: int = 0,
) -> ResolutionContext:
    """Helper para callers que tienen rows directos de Supabase.

    Mantiene el resolver puro (recibe ResolutionContext) y centraliza la
    extracción de campos en un solo lugar (DRY entre dispatcher + tests).
    """
    conv = conversation or {}
    c = cart or {}
    contact_row = contact or {}
    order_row = order or {}
    payment_row = payment or {}

    items_count = 0
    raw_items = c.get("items_count") or c.get("line_items_count")
    if isinstance(raw_items, int):
        items_count = raw_items
    elif isinstance(c.get("items"), list):
        items_count = len(c["items"])

    # Schema real: shipping_meta JSONB contiene quoted_options + carrier + rate_id.
    # Cotización está disponible cuando hay quoted_options (pre-select_carrier) O
    # cuando ya hay shipping_cents > 0 (post-select_carrier).
    #
    # 2026-06-26 (founder, hallazgo live): `requires_requote=True` (cliente agregó/
    # quitó items o cambió dirección post-cotización) INVALIDA la cotización aunque
    # `shipping_meta` conserve quoted_options STALE. Sin esto, has_quote seguía True
    # → el bot quedaba en CARRIER_SELECTION con opciones viejas y la conversación se
    # rompía (pedía ciudad de nuevo, deflectía ante "genérame el link"). Gateando por
    # requires_requote, el resolver enruta a SHIPPING_QUOTE → recotización limpia.
    _meta = c.get("shipping_meta") or {}
    _requires_requote = bool(c.get("requires_requote"))
    has_quote = (not _requires_requote) and bool(
        _meta.get("quoted_options")
        or c.get("shipping_cents")
        or c.get("shipping_quote_id")
    )
    has_carrier = (not _requires_requote) and bool(
        _meta.get("carrier")
        or c.get("carrier_id")
        or c.get("carrier_code")
    )
    has_link = bool(c.get("payment_link") or c.get("wompi_link_id"))

    # Schema real: contact tiene `document_number` (no `document`).
    # email opcional — document_number + address son los críticos para envío.
    has_required_pii = bool(
        contact_row.get("name")
        and (
            contact_row.get("document_number")
            or contact_row.get("document")
            or contact_row.get("email")
        )
        and contact_row.get("address")
    )

    has_order = bool(order_row.get("id"))
    payment_status = (payment_row.get("status") or "").lower() or None

    return ResolutionContext(
        conversation_status=(conv.get("status") or "bot_active").lower(),
        has_prior_inbound=history_len > 0,
        history_len=history_len,
        cart_status=(c.get("status") or None),
        cart_items_count=items_count,
        cart_payment_method=(c.get("payment_method") or None),
        cart_has_shipping_quote=has_quote,
        cart_has_carrier_selected=has_carrier,
        cart_has_payment_link=has_link,
        contact_consent_given=bool(contact_row.get("consent_given")),
        contact_has_required_pii=has_required_pii,
        has_active_order=has_order,
        payment_status=payment_status,
    )
