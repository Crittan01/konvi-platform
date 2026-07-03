"""ADR-0026 Pieza B — Renderizador CANÓNICO del estado del carrito.

Un único lugar que rinde el estado del carrito a texto WhatsApp tras una mutación
(add/remove/qty). Reemplaza la composición fragmentada de subtotales/envío que vivía
dispersa en `compose_outbound_from_resolution` (subtotal parcial) y que repreguntaba la
ciudad aunque el cart ya la tuviera persistida (ADR-0026 Pieza A).

Decide en UN solo lugar "¿pregunto la ciudad o no?" leyendo el destino persistido vía
`get_shipping_destination` (cart > contact > None). Es **función pura** (sin IO): recibe
el cart + contact + opciones ya cargados.

Contrato del `cart` esperado (de `tools.cart_tool.get_cart_with_items`):
    {subtotal_cents, shipping_cents, total_cents, requires_requote, discount_cents,
     coupon_code, shipping_meta, items: [{quantity, unit_price_cents,
     product: {title}, variation: {label}}]}
"""
from __future__ import annotations

from typing import Optional

# F36 — fuente única de formateo COP. Antes copia local; format_cents_cop es
# byte-idéntico para centavos enteros y None→'$0' (mismo fallback).
from text_utils import format_cents_cop as _cop


def _item_bullets(items: list[dict]) -> list[str]:
    """Bullets de líneas del carrito con line total + precio unitario (si qty>1).
    Mismo formato que compose_outbound_from_resolution para paridad visual."""
    bullets: list[str] = []
    for it in items or []:
        qty = int(it.get("quantity") or 1)
        unit_cents = int(it.get("unit_price_cents") or 0)
        title = ((it.get("product") or {}).get("title")) or it.get("title") or "Producto"
        label = ((it.get("variation") or {}).get("label")) or it.get("variant_label") or ""
        label_str = f" de {label}" if label else ""
        line_total = qty * unit_cents
        unit_str = f" (${unit_cents // 100:,} c/u)".replace(",", ".") if (qty > 1 and unit_cents > 0) else ""
        bullets.append(f"* {qty} *{title}*{label_str} — *{_cop(line_total)}*{unit_str}")
    return bullets


def _shipping_option_bullets(options: list[dict]) -> list[str]:
    """Bullets de opciones de envío recotizadas (carrier + costo + eta). Mismo formato
    que el bypass pre-LLM de shipping para paridad."""
    bullets: list[str] = []
    for o in options or []:
        price = int(o.get("price_cop") or 0)
        price_str = f"${price:,}".replace(",", ".")
        eta = o.get("eta_date") or ""
        eta_str = f" ({eta})" if eta else ""
        bullets.append(f"* *{o.get('carrier')}*{eta_str}: *{price_str} COP*")
    return bullets


def render_cart_facts_for_llm(
    cart: dict,
    contact: Optional[dict] = None,
) -> str:
    """ADR-0026 Pieza C — snapshot FACTUAL del carrito para inyectar en el system prompt.

    NO es texto al cliente: son hechos para que el LLM no invente subtotales ni repregunte
    la ciudad. Función pura.
    """
    from tools.cart_tool import get_shipping_destination

    cart = cart or {}
    items = cart.get("items") or []
    if not items:
        return ""
    lines = ["Items en el carrito:"]
    for it in items:
        qty = int(it.get("quantity") or 1)
        unit_cents = int(it.get("unit_price_cents") or 0)
        title = ((it.get("product") or {}).get("title")) or "Producto"
        label = ((it.get("variation") or {}).get("label")) or ""
        lbl = f" ({label})" if label else ""
        lines.append(f"- {qty}x {title}{lbl}: {_cop(qty * unit_cents)}")
    lines.append(f"Subtotal real del carrito: {_cop(cart.get('subtotal_cents'))}")

    requires_requote = bool(cart.get("requires_requote"))
    shipping_cents = int(cart.get("shipping_cents") or 0)
    meta = cart.get("shipping_meta") or {}
    dest = get_shipping_destination(cart, contact)
    city = (dest or {}).get("city")

    if shipping_cents > 0 and not requires_requote:
        carrier = str(meta.get("carrier") or "").strip()
        carrier_str = f" ({carrier})" if carrier else ""
        lines.append(
            f"Envío: cotizado{carrier_str} {_cop(shipping_cents)} — "
            f"TOTAL {_cop(cart.get('total_cents'))}"
        )
    elif requires_requote:
        lines.append("Envío: PENDIENTE de recotizar (el cliente cambió el carrito)")
    else:
        lines.append("Envío: aún no cotizado")
    if city:
        lines.append(f"Ciudad de entrega ya conocida: {city} — NO la repreguntes")
    return "\n".join(lines)


def render_cart_state_snapshot(
    *,
    cart: dict,
    contact: Optional[dict] = None,
    destination: Optional[dict] = None,
    customer_name: Optional[str] = None,
    lead: Optional[str] = None,
    requote_options: Optional[list[dict]] = None,
) -> str:
    """Rinde el estado del carrito tras una mutación, de forma coherente y completa.

    Estructura:
      {lead}
      {bullets de TODOS los items del carrito}
      Subtotal: *$REAL*   [+ Descuento si cupón]
      {línea de envío — uno de 3 modos}

    Modos de envío (decisión única):
      (i)   envío cotizado vigente (shipping_cents>0 y NOT requires_requote)
            → muestra carrier + costo + TOTAL.
      (ii)  requires_requote=True (o sin envío) CON destino conocido
            → si hay `requote_options`: "Recalculé el envío a {city}:" + opciones.
            → si no: "Como cambió tu pedido, recalculo el envío a *{city}*."
      (iii) sin destino conocido → pide la ciudad UNA vez.

    Args:
        cart: dict de get_cart_with_items (con items + totales + shipping_meta).
        contact: para el fallback de destino (get_shipping_destination).
        destination: destino ya resuelto {city, dane_code, ...}; si None se resuelve.
        customer_name: primer nombre para el saludo (si lead es None).
        lead: línea de apertura. Default: "Listo, {name}. Tu pedido va así:".
        requote_options: opciones de envío recotizadas a presentar (modo ii).
    """
    from tools.cart_tool import get_shipping_destination

    cart = cart or {}
    items = cart.get("items") or []
    subtotal_cents = int(cart.get("subtotal_cents") or 0)
    shipping_cents = int(cart.get("shipping_cents") or 0)
    total_cents = int(cart.get("total_cents") or 0)
    requires_requote = bool(cart.get("requires_requote"))
    discount_cents = int(cart.get("discount_cents") or 0)
    coupon_code = cart.get("coupon_code") or ""
    meta = cart.get("shipping_meta") or {}

    if destination is None:
        destination = get_shipping_destination(cart, contact)
    dest_city = (destination or {}).get("city") if destination else None

    # Encabezado.
    if lead is None:
        lead = f"Listo, {customer_name}. Tu pedido va así:" if customer_name else "Tu pedido va así:"

    parts: list[str] = [lead]
    bullets = _item_bullets(items)
    if bullets:
        parts.append("\n".join(bullets))

    # Subtotal real + descuento.
    money_lines = [f"Subtotal: *{_cop(subtotal_cents)}*"]
    if discount_cents > 0:
        disc_label = f" ({coupon_code})" if coupon_code else ""
        money_lines.append(f"Descuento{disc_label}: -{_cop(discount_cents)}")

    # Línea de envío — decisión única.
    #   (i)   envío cotizado vigente → carrier + costo + TOTAL.
    #   (ii)  requires_requote=True (HUBO envío que se invalidó) → recotizar.
    #   (iii) sin envío aún (carrito en construcción) → pedir ciudad UNA vez.
    # Clave (bug founder): "recalculo el envío" SOLO si requires_requote — nunca en el
    # primer add, aunque el contacto tenga una dirección guardada.
    shipping_has_quote = shipping_cents > 0 and not requires_requote
    parts.append("\n".join(money_lines))
    if shipping_has_quote:
        carrier = str(meta.get("carrier") or "").strip()
        carrier_str = f" ({carrier})" if carrier else ""
        # Reescribir la última sección con la línea de envío + total.
        parts[-1] = "\n".join(
            money_lines
            + [f"Envío{carrier_str}: {_cop(shipping_cents)}", f"*TOTAL: {_cop(total_cents)}*"]
        )
    elif requires_requote and dest_city and requote_options:
        opt_bullets = _shipping_option_bullets(requote_options)
        parts.append(
            f"Recalculé el envío a *{dest_city}*:\n\n"
            + "\n".join(opt_bullets)
            + "\n\n¿Cuál prefieres?"
        )
    elif requires_requote and dest_city:
        parts.append(
            f"Como cambió tu pedido, recalculo el envío a *{dest_city}*. "
            "Dame un segundo y te muestro las opciones actualizadas."
        )
    elif requires_requote:
        parts.append(
            "Como cambió tu pedido, necesito recotizar el envío. "
            "¿A qué ciudad te lo enviamos?"
        )
    else:
        parts.append(
            "¿Quieres agregar algo más o ya coordinamos el envío? "
            "Cuéntame a qué ciudad te lo enviamos."
        )

    return "\n\n".join(parts)
