"""Handlers de tools de cierre de pedido.

Tools cubiertos:
  - ``render_summary``       → genera el resumen estructurado desde el cart
  - ``confirm_order``        → transición cart → checkout + crear orden + Wompi link
  - ``cancel_order``         → cart → cancelled
  - ``escalate_to_human``    → cambia status conversation a human_takeover

El resumen es 100% determinístico desde ``ctx.cart`` + ``ctx.contact_record``.
NO se delega al LLM porque el LLM no es fuente de verdad de precios/totales
(regla del repo, ``.context/03-rules.md``).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from supabase import Client

from core.context import ConversationContext
from persistence.carts_repo import CartsRepo

logger = logging.getLogger("orchestrator.tools_v2.order")


# ── Formatters ──────────────────────────────────────────────────────────────


def _format_cop_cents(cents: int) -> str:
    """Formato Colombia: $X.XXX (sin centavos, separador miles punto)."""
    pesos = int(round(cents / 100))
    return f"${pesos:,}".replace(",", ".") + " COP"


def _format_phone_co(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("57") and len(digits) == 12:
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+{digits}"


def _format_address_for_summary(addr: Optional[dict]) -> str:
    if not isinstance(addr, dict):
        return ""
    parts: list[str] = []
    street = str(addr.get("street") or "").strip()
    if street:
        parts.append(street)
    btype = str(addr.get("building_type") or "").strip().lower()
    sub: list[str] = []
    if btype == "conjunto":
        if addr.get("complex_name"):
            sub.append(str(addr["complex_name"]))
        if addr.get("tower"):
            t = str(addr["tower"])
            sub.append(t if t.lower().startswith("torre") else f"Torre {t}")
        if addr.get("apartment"):
            sub.append(f"Apto {addr['apartment']}")
    elif btype == "edificio":
        if addr.get("complex_name"):
            sub.append(str(addr["complex_name"]))
        if addr.get("apartment"):
            sub.append(f"Apto {addr['apartment']}")
    if sub:
        parts.append(", ".join(sub))
    if addr.get("neighborhood"):
        parts.append(str(addr["neighborhood"]))
    if addr.get("city"):
        parts.append(str(addr["city"]))
    return " — ".join(parts)


# ── Handlers ────────────────────────────────────────────────────────────────


async def handle_render_summary(
    *,
    ctx: ConversationContext,
    args: dict,
    supabase: Client,
) -> dict:
    """Construye el texto del resumen y lo retorna al LLM como function_response.

    El LLM lo enviará verbatim al cliente (la instrucción en el prompt es
    "render_summary devuelve el texto exacto a enviar; no parafrasees").
    """
    if not ctx.cart or not ctx.cart.is_open:
        return {"ok": False, "error": "no_open_cart"}
    if not ctx.cart.items:
        return {"ok": False, "error": "empty_cart"}

    # Lookup títulos + variant labels desde catálogo (ctx.catalog).
    var_index: dict[str, dict] = {}
    prod_index: dict[str, dict] = {}
    for prod in ctx.catalog or []:
        prod_index[str(prod.get("id"))] = prod
        for v in prod.get("variants") or []:
            var_index[str(v.get("id"))] = v

    lines: list[str] = ["📋 *Resumen de tu pedido:*", "", "*Productos:*"]
    for item in ctx.cart.items:
        prod = prod_index.get(item.product_id, {})
        var = var_index.get(item.variation_id, {})
        title = str(prod.get("title") or "Producto").strip()
        var_label = ""
        attrs = var.get("attributes") or {}
        if isinstance(attrs, dict) and attrs:
            var_label = ", ".join(f"{k}: {v}" for k, v in attrs.items())
        elif var.get("label"):
            var_label = str(var["label"])

        line_total = item.line_total_cents
        label = f"• {item.quantity}x {title}"
        if var_label and var_label.lower() not in {"estandar", "estándar"}:
            label += f" ({var_label})"
        label += f": {_format_cop_cents(line_total)}"
        lines.append(label)

    lines.append("")
    lines.append(f"Subtotal: {_format_cop_cents(ctx.cart.subtotal_cents)}")
    lines.append(f"Envío: {_format_cop_cents(ctx.cart.shipping_cents)}")
    lines.append(f"*TOTAL: {_format_cop_cents(ctx.cart.total_cents)}*")

    # Datos del cliente
    cr = ctx.contact_record or {}
    name = str(cr.get("name") or "").strip()
    email = str(cr.get("email") or "").strip()
    phone = _format_phone_co(cr.get("phone") or ctx.customer_phone)
    doc_t = str(cr.get("document_type") or "").strip().upper()
    doc_n = str(cr.get("document_number") or "").strip()
    addr_line = _format_address_for_summary(cr.get("address"))

    if any([name, email, phone, doc_t and doc_n, addr_line]):
        lines.append("")
        lines.append("*Datos de envío:*")
        if name:
            lines.append(f"• Nombre: {name}")
        if email:
            lines.append(f"• Correo: {email}")
        if phone:
            lines.append(f"• Celular: {phone}")
        if doc_t and doc_n:
            lines.append(f"• Documento: {doc_t} {doc_n}")
        if addr_line:
            lines.append(f"• Dirección: {addr_line}")

    lines.append("")
    lines.append("¿Confirmas que los datos están correctos para generar tu link de pago?")
    text = "\n".join(lines)

    return {"ok": True, "summary_text": text, "total_cents": ctx.cart.total_cents}


async def handle_confirm_order(
    *,
    ctx: ConversationContext,
    args: dict,
    supabase: Client,
    repo: CartsRepo,
) -> dict:
    """Crea orden + payment link Wompi. Transiciona cart → checkout."""
    if not ctx.cart or not ctx.cart.is_open:
        return {"ok": False, "error": "no_open_cart"}
    if not ctx.cart.items:
        return {"ok": False, "error": "empty_cart"}
    cr = ctx.contact_record or {}
    if not cr.get("consent_given"):
        return {"ok": False, "error": "consent_required"}

    # Construir items para la orden (snapshot del cart).
    items_payload: list[dict] = []
    for item in ctx.cart.items:
        # Lookup título para snapshot
        title = "Producto"
        for prod in ctx.catalog or []:
            if str(prod.get("id")) == item.product_id:
                title = str(prod.get("title") or "Producto")
                for v in prod.get("variants") or []:
                    if str(v.get("id")) == item.variation_id:
                        attrs = v.get("attributes") or {}
                        if isinstance(attrs, dict) and attrs:
                            title += " — " + ", ".join(
                                f"{k}: {v_}" for k, v_ in attrs.items()
                            )
                        break
                break
        items_payload.append({
            "title": title,
            "unit_price": item.unit_price_cents / 100.0,
            "quantity": item.quantity,
            "product_id": item.product_id,
            "variation_id": item.variation_id,
        })

    # POST a la API de orders (sigue siendo la ruta canónica de creación).
    try:
        from tools.payment_link_tool import handle_payment_link_if_applicable
    except Exception as exc:
        return {"ok": False, "error": f"payment_link_unavailable: {exc}"}

    pl = await handle_payment_link_if_applicable(
        tenant_id=ctx.tenant_id,
        contact_id=ctx.contact_id,
        conversation_id=ctx.conversation_id,
        contact_name=cr.get("name"),
        total_in_cents=ctx.cart.total_cents,
        shipping_cost_cents=ctx.cart.shipping_cents,
        notes=None,
        supabase=supabase,
        verified_ctx={"items": [
            {
                "title": ip["title"],
                "unit_price_cents": int(round(ip["unit_price"] * 100)),
                "quantity": ip["quantity"],
                "product_id": ip["product_id"],
                "variation_id": ip["variation_id"],
                "variant_label": None,
            }
            for ip in items_payload
        ]},
    )
    if not pl:
        # NO prometer asesor en el message — eso fuerza al cliente a esperar
        # un humano que quizá no llega. En cambio, mensaje técnico neutro:
        # el orquestador puede reintentar o el cliente puede pedir
        # explícitamente hablar con alguien (que sí dispara escalate_to_human).
        return {
            "ok": False,
            "error": "payment_link_failed",
            "message": (
                "Tuve un problema técnico generando tu link de pago. "
                "Por favor, intentémoslo en un momento."
            ),
        }

    # Transition cart a checkout (idempotente — si falla version mismatch,
    # asumimos que otro turno ya lo cerró).
    try:
        repo.transition_status(
            tenant_id=ctx.tenant_id,
            cart_id=ctx.cart.id,
            new_status="checkout",
            expected_version=ctx.cart.version,
        )
    except Exception as exc:
        logger.warning("[order_tools.confirm] cart transition failed: %s", exc)

    return {
        "ok": True,
        "checkout_url": pl.checkout_url,
        "order_id": pl.order_id,
        "amount_in_cents": pl.amount_in_cents,
        "response_text": pl.response_text,
    }


async def handle_cancel_order(
    *,
    ctx: ConversationContext,
    args: dict,
    repo: CartsRepo,
) -> dict:
    if not ctx.cart:
        return {"ok": True, "message": "no había carrito activo"}
    # Liberar reservas de stock activas del cart antes de cerrar.
    # Otros clientes podrán comprarlas inmediatamente.
    try:
        released = repo.release_reservations_for_cart(cart_id=ctx.cart.id)
        if released > 0:
            logger.info(
                "[order_tools.cancel] liberadas %d reservas del cart=%s",
                released, ctx.cart.id,
            )
    except Exception as exc:
        logger.warning("[order_tools.cancel] release reservations failed: %s", exc)

    try:
        repo.transition_status(
            tenant_id=ctx.tenant_id,
            cart_id=ctx.cart.id,
            new_status="cancelled",
            expected_version=ctx.cart.version,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


async def handle_escalate_to_human(
    *,
    ctx: ConversationContext,
    args: dict,
    supabase: Client,
) -> dict:
    """Marca la conversación como ``human_takeover`` (contrato canónico §3)."""
    reason = str(args.get("reason") or "unspecified")
    supabase.table("conversations").update(
        {"status": "human_takeover"}
    ).eq("id", ctx.conversation_id).execute()
    logger.info(
        "[order_tools.escalate] conv=%s reason=%s", ctx.conversation_id, reason,
    )
    return {"ok": True, "reason": reason}
