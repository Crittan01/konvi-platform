"""Prompt builder per-state (rev. 109 Día 2).

Compone: identity + time_greeting + customer_context + state_specific
+ catalog + carriers + payment_methods + safety + style.

Objetivo de tamaño: 6-10KB total por estado (vs 19KB monolito).
Estados livianos (PII, PAYMENT, POST_PAYMENT) → ~5-6KB.
Estados pesados (CART_BUILDING, EXPLORING — necesitan catálogo) → ~8-10KB.

API:
    prompt = build_prompt_for_state(
        state=AgenticState.CART_BUILDING,
        tenant_name="KAIU Living Natural",
        catalog=catalog,
        contact_record=contact,
        carriers=carriers,
        payment_methods=payment_methods,
    )
"""
from __future__ import annotations

from typing import Optional

from agentic.state_machine.states import AgenticState
from agentic.prompt.blocks import (
    identity_block,
    time_greeting_block,
    safety_block,
    style_block,
    catalog_section,
    customer_section,
    carriers_section,
    payment_methods_section,
    coupons_section,
    business_ops_section,
)
from agentic.prompt.states import (
    greeting_prompt,
    exploring_prompt,
    cart_building_prompt,
    pii_collection_prompt,
    shipping_quote_prompt,
    carrier_selection_prompt,
    payment_prompt,
    post_payment_prompt,
    human_handoff_prompt,
)


_STATE_PROMPT_MAP = {
    AgenticState.GREETING: greeting_prompt,
    AgenticState.EXPLORING: lambda _tn: exploring_prompt(),
    AgenticState.CART_BUILDING: lambda _tn: cart_building_prompt(),
    AgenticState.PII_COLLECTION: lambda _tn: pii_collection_prompt(),
    AgenticState.SHIPPING_QUOTE: lambda _tn: shipping_quote_prompt(),
    AgenticState.CARRIER_SELECTION: lambda _tn: carrier_selection_prompt(),
    AgenticState.PAYMENT: lambda _tn: payment_prompt(),
    AgenticState.POST_PAYMENT: lambda _tn: post_payment_prompt(),
    AgenticState.HUMAN_HANDOFF: lambda _tn: human_handoff_prompt(),
}


# Estados que NO necesitan catálogo completo en el prompt (reducción tamaño).
# Igual reciben el catalog si se pasa (defensa) — solo no lo inyectamos por
# default en esos estados.
_NO_CATALOG_STATES = frozenset({
    AgenticState.PII_COLLECTION,
    AgenticState.SHIPPING_QUOTE,
    AgenticState.CARRIER_SELECTION,
    AgenticState.PAYMENT,
    AgenticState.POST_PAYMENT,
    AgenticState.HUMAN_HANDOFF,
})


# Estados que NO necesitan carriers ni payment_methods (reducción tamaño).
_NO_CARRIERS_STATES = frozenset({
    AgenticState.GREETING,
    AgenticState.EXPLORING,
    AgenticState.CART_BUILDING,
    AgenticState.PII_COLLECTION,
    AgenticState.POST_PAYMENT,
    AgenticState.HUMAN_HANDOFF,
})


_NO_PAYMENT_METHODS_STATES = frozenset({
    AgenticState.GREETING,
    AgenticState.EXPLORING,
    AgenticState.CART_BUILDING,
    AgenticState.PII_COLLECTION,
    AgenticState.SHIPPING_QUOTE,
    AgenticState.CARRIER_SELECTION,
    AgenticState.POST_PAYMENT,
    AgenticState.HUMAN_HANDOFF,
})


# Cupones solo donde el cliente puede preguntar o aplicar (founder 2026-05-28).
# Excluye estados terminales/transaccionales puros donde mencionar promo confunde.
_NO_COUPONS_STATES = frozenset({
    AgenticState.PII_COLLECTION,
    AgenticState.SHIPPING_QUOTE,
    AgenticState.CARRIER_SELECTION,
    AgenticState.PAYMENT,
    AgenticState.POST_PAYMENT,
    AgenticState.HUMAN_HANDOFF,
})


# Business ops block (shipping_origin + store_locations + support_schedule + social_links)
# se inyecta en estados conversacionales donde el cliente típicamente pregunta
# "¿de dónde despachan? / ¿tienen tienda física? / ¿horario? / ¿redes?". Excluye
# estados transaccionales puros donde el bloque agrega ruido sin uso (PII/SHIPPING/
# CARRIER/PAYMENT/HANDOFF). Decisión Q3 ADR-0024 (root-cause analysis wujbdgrhk —
# robustez sobre footprint: ~3-5KB tokens extra es aceptable, cero improvisación
# en preguntas comunes prima).
_BUSINESS_OPS_STATES = frozenset({
    AgenticState.GREETING,
    AgenticState.EXPLORING,
    AgenticState.CART_BUILDING,
    AgenticState.POST_PAYMENT,
})


def build_prompt_for_state(
    *,
    state: AgenticState,
    tenant_name: str,
    tenant_pitch: Optional[str] = None,
    tenant_tone: Optional[str] = None,
    agent_name: str = "Sara Camila",
    catalog: Optional[list[dict]] = None,
    contact_record: Optional[dict] = None,
    carriers: Optional[list[dict]] = None,
    payment_methods: Optional[dict] = None,
    server_greeting: Optional[str] = None,
    active_coupons: Optional[list[dict]] = None,
    # Fase 0 finiquito 2026-06-23 — business_ops kwargs (audit-finiquito
    # root-cause analysis wujbdgrhk). Sin estos, V3 per-state genera prompt
    # sin SOBRE LA TIENDA y bot improvisa horarios/despacho/sedes.
    shipping_origin: Optional[dict] = None,
    store_locations: Optional[list[dict]] = None,
    store_type: Optional[str] = None,
    support_schedule: Optional[dict] = None,
    social_links: Optional[dict] = None,
    after_hours_message: Optional[str] = None,
) -> str:
    """Construye el system prompt específico para un estado.

    Composición (rev. Fase 3 finiquito 2026-06-23 — reorden anti-improvisation):
      1. identity_block
      2. time_greeting_block (solo GREETING + EXPLORING + POST_PAYMENT)
      3. customer_section
      4. business_ops_section (solo _BUSINESS_OPS_STATES) — ANTES del mini-prompt
         del estado para anchor temprano de contexto factual del negocio (XML tags
         + regla anti-improvisation). Fase 3 ataque P4: LLM ignora dato presente
         cuando está al medio/fondo del prompt + tiene sesgo training-data.
      5. state-specific mini-prompt
      6. catalog (si aplica al estado)
      7. carriers (si aplica)
      8. payment_methods (si aplica)
      9. coupons (si aplica)
      10. safety + style (universal)
    """
    pitch = tenant_pitch or f"asesora de {tenant_name}"
    tone = tenant_tone or "cordial y profesional, en español Colombia"

    parts: list[str] = []

    parts.append(identity_block(
        agent_name=agent_name, tenant_name=tenant_name,
        pitch=pitch, tone=tone,
    ))

    # Saludo time-aware solo donde es relevante.
    if state in (
        AgenticState.GREETING, AgenticState.EXPLORING, AgenticState.POST_PAYMENT,
    ):
        greeting_block, _ = time_greeting_block(server_greeting)
        parts.append(greeting_block)

    parts.append(customer_section(contact_record, tenant_name=tenant_name))

    # Business ops (operaciones del negocio) — solo estados conversacionales
    # donde el cliente típicamente pregunta. Decisión Q3 ADR-0024.
    # Fase 3 finiquito 2026-06-23 — ANCLA TEMPRANA: insertado ANTES del
    # mini-prompt del estado para que LLM lo procese como verdad ya conocida
    # del negocio (no como info opcional al fondo). XML tags + regla
    # anti-improvisation dentro del wrapper (ver blocks.business_ops_section).
    if state in _BUSINESS_OPS_STATES:
        ops_block = business_ops_section(
            tenant_name=tenant_name,
            shipping_origin=shipping_origin,
            store_locations=store_locations,
            store_type=store_type,
            support_schedule=support_schedule,
            social_links=social_links,
            after_hours_message=after_hours_message,
        )
        if ops_block:
            parts.append(ops_block)

    # Mini-prompt del estado (POST business_ops para que la lógica del estado
    # opere sobre contexto factual ya anclado).
    state_fn = _STATE_PROMPT_MAP.get(state)
    if state_fn:
        parts.append(state_fn(tenant_name))

    # Catálogo solo donde el cliente lo necesita (browsing/cart).
    if state not in _NO_CATALOG_STATES:
        parts.append(catalog_section(catalog))

    # Carriers solo en SHIPPING_QUOTE + CARRIER_SELECTION + PAYMENT.
    if state not in _NO_CARRIERS_STATES:
        parts.append(carriers_section(carriers))

    # Métodos de pago solo en PAYMENT.
    if state not in _NO_PAYMENT_METHODS_STATES:
        parts.append(payment_methods_section(payment_methods))

    # Cupones donde aplica (GREETING/EXPLORING/CART_BUILDING).
    if state not in _NO_COUPONS_STATES:
        parts.append(coupons_section(active_coupons))

    parts.append(safety_block())
    parts.append(style_block(tone))

    return "\n".join(parts)
